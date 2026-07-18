import Foundation

enum ProfileBuilder {
    static let navigationDescription = "Codex Gamepad — navigation (8BitDo Ultimate 2C)"
    static let receiverDescription = "Codex Gamepad — speak/stop (Karabiner 16 receiver)"

    static func build(baseData: Data, settings: GamepadSettings) throws -> Data {
        guard var root = try JSONSerialization.jsonObject(with: baseData) as? [String: Any],
              var rules = root["rules"] as? [[String: Any]],
              let navigationIndex = rules.firstIndex(where: { $0["description"] as? String == navigationDescription }),
              let receiverIndex = rules.firstIndex(where: { $0["description"] as? String == receiverDescription }),
              let navigationTemplate = (rules[navigationIndex]["manipulators"] as? [[String: Any]])?.first,
              let receiverTemplate = (rules[receiverIndex]["manipulators"] as? [[String: Any]])?.first,
              let navigationConditions = navigationTemplate["conditions"] as? [[String: Any]],
              let receiverConditions = receiverTemplate["conditions"] as? [[String: Any]],
              let receiverTo = receiverTemplate["to"] as? [[String: Any]]
        else {
            throw SetupError.invalidProfile("required rules or templates are missing")
        }

        var navigationManipulators: [[String: Any]] = []
        var receiverManipulators: [[String: Any]] = []
        for input in ControllerInput.all {
            let action = settings.action(for: input)
            if action == .unmapped { continue }
            let from: [String: Any] = [
                input.eventKey: input.eventValue,
                "modifiers": ["optional": ["any"]],
            ]
            if action == .speak {
                receiverManipulators.append([
                    "type": "basic",
                    "from": from,
                    "to": receiverTo,
                    "conditions": receiverConditions,
                ])
            } else {
                navigationManipulators.append([
                    "type": "basic",
                    "from": from,
                    "to": [try keyEvent(for: action, input: input, settings: settings)],
                    "conditions": navigationConditions,
                ])
            }
        }
        guard !receiverManipulators.isEmpty else {
            throw SetupError.invalidProfile("assign Speak / Stop to at least one controller input")
        }
        guard !navigationManipulators.isEmpty else {
            throw SetupError.invalidProfile("assign at least one keyboard action")
        }

        rules[navigationIndex]["manipulators"] = navigationManipulators
        rules[receiverIndex]["manipulators"] = receiverManipulators
        root["rules"] = rules
        return try JSONSerialization.data(
            withJSONObject: root,
            options: [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
        ) + Data([0x0a])
    }

    private static func keyEvent(
        for action: BindingAction,
        input: ControllerInput,
        settings: GamepadSettings
    ) throws -> [String: Any] {
        switch action {
        case .arrowUp: ["key_code": "up_arrow"]
        case .arrowDown: ["key_code": "down_arrow"]
        case .arrowLeft: ["key_code": "left_arrow"]
        case .arrowRight: ["key_code": "right_arrow"]
        case .dictate: ["key_code": "d", "modifiers": ["left_control", "left_shift"]]
        case .escape: ["key_code": "escape"]
        case .tab: ["key_code": "tab"]
        case .commandMenu: ["key_code": "k", "modifiers": ["left_command"]]
        case .previousTask: ["key_code": "open_bracket", "modifiers": ["left_command", "left_shift"]]
        case .nextTask: ["key_code": "close_bracket", "modifiers": ["left_command", "left_shift"]]
        case .send: ["key_code": "return_or_enter", "repeat": false]
        case .space: ["key_code": "spacebar"]
        case .deleteBackward: ["key_code": "delete_or_backspace"]
        case .pageUp: ["key_code": "page_up"]
        case .pageDown: ["key_code": "page_down"]
        case .custom:
            try customKeyEvent(settings.customShortcuts[input.id] ?? "")
        case .speak, .unmapped:
            throw SetupError.invalidProfile("unsupported keyboard action \(action.rawValue)")
        }
    }

    private static func customKeyEvent(_ shortcut: String) throws -> [String: Any] {
        let parts = shortcut.lowercased().split(separator: "+").map {
            $0.trimmingCharacters(in: .whitespacesAndNewlines)
        }.filter { !$0.isEmpty }
        guard let keyName = parts.last else {
            throw SetupError.invalidProfile("enter a custom shortcut such as cmd+shift+p")
        }
        let modifierNames: [String: String] = [
            "cmd": "left_command",
            "command": "left_command",
            "shift": "left_shift",
            "ctrl": "left_control",
            "control": "left_control",
            "opt": "left_option",
            "option": "left_option",
            "alt": "left_option",
        ]
        var modifiers: [String] = []
        for part in parts.dropLast() {
            guard let modifier = modifierNames[part] else {
                throw SetupError.invalidProfile("unsupported custom modifier \(part)")
            }
            if !modifiers.contains(modifier) { modifiers.append(modifier) }
        }
        let namedKeys: [String: String] = [
            "return": "return_or_enter",
            "enter": "return_or_enter",
            "esc": "escape",
            "escape": "escape",
            "tab": "tab",
            "space": "spacebar",
            "delete": "delete_or_backspace",
            "backspace": "delete_or_backspace",
            "up": "up_arrow",
            "down": "down_arrow",
            "left": "left_arrow",
            "right": "right_arrow",
            "pageup": "page_up",
            "pagedown": "page_down",
            "home": "home",
            "end": "end",
            "[": "open_bracket",
            "]": "close_bracket",
        ]
        let isLetter = keyName.count == 1 && keyName.first?.isLetter == true
        let isNumber = keyName.count == 1 && keyName.first?.isNumber == true
        guard let keyCode = namedKeys[keyName] ?? ((isLetter || isNumber) ? keyName : nil) else {
            throw SetupError.invalidProfile("unsupported custom key \(keyName)")
        }
        var event: [String: Any] = ["key_code": keyCode]
        if !modifiers.isEmpty { event["modifiers"] = modifiers }
        return event
    }
}
