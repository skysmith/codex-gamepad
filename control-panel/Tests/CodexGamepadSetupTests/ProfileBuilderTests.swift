import Foundation
import Testing
@testable import CodexGamepadSetup

@Test func profileBuilderMovesSpeechAndPreservesScope() throws {
    let base: [String: Any] = [
        "title": "Codex Gamepad",
        "rules": [
            [
                "description": ProfileBuilder.navigationDescription,
                "manipulators": [[
                    "type": "basic",
                    "from": ["pointing_button": "button1"],
                    "to": [["key_code": "escape"]],
                    "conditions": [["type": "frontmost_application_if", "bundle_identifiers": ["^com\\.openai\\.codex$"]]],
                ]],
            ],
            [
                "description": ProfileBuilder.receiverDescription,
                "manipulators": [[
                    "type": "basic",
                    "from": ["pointing_button": "button4"],
                    "to": [["send_user_command": ["payload": ["command": "codex_speak_last_response"]]]],
                    "conditions": [["type": "device_if", "identifiers": [["is_game_pad": true]]]],
                ]],
            ],
        ],
    ]
    var settings = GamepadSettings()
    settings.bindings["button_x"] = BindingAction.escape.rawValue
    settings.bindings["button_r4"] = BindingAction.speak.rawValue
    let data = try ProfileBuilder.build(
        baseData: JSONSerialization.data(withJSONObject: base),
        settings: settings
    )
    let root = try #require(JSONSerialization.jsonObject(with: data) as? [String: Any])
    let rules = try #require(root["rules"] as? [[String: Any]])
    let receiver = try #require(rules.first { $0["description"] as? String == ProfileBuilder.receiverDescription })
    let manipulators = try #require(receiver["manipulators"] as? [[String: Any]])
    let from = try #require(manipulators.first?["from"] as? [String: Any])
    #expect(from["pointing_button"] as? String == "button6")
}

@Test func profileBuilderRequiresSpeechBinding() throws {
    let root: [String: Any] = [
        "rules": [
            [
                "description": ProfileBuilder.navigationDescription,
                "manipulators": [["conditions": [], "to": [], "from": [:]]],
            ],
            [
                "description": ProfileBuilder.receiverDescription,
                "manipulators": [["conditions": [], "to": [["send_user_command": [:]]], "from": [:]]],
            ],
        ],
    ]
    var settings = GamepadSettings()
    settings.bindings = settings.bindings.mapValues { _ in BindingAction.escape.rawValue }
    #expect(throws: SetupError.self) {
        try ProfileBuilder.build(
            baseData: JSONSerialization.data(withJSONObject: root),
            settings: settings
        )
    }
}

@Test func profileBuilderAcceptsAllowlistedCustomShortcut() throws {
    let base: [String: Any] = [
        "rules": [
            [
                "description": ProfileBuilder.navigationDescription,
                "manipulators": [["conditions": [], "to": [], "from": [:]]],
            ],
            [
                "description": ProfileBuilder.receiverDescription,
                "manipulators": [["conditions": [], "to": [["send_user_command": [:]]], "from": [:]]],
            ],
        ],
    ]
    var settings = GamepadSettings()
    settings.bindings["button_r4"] = BindingAction.custom.rawValue
    settings.customShortcuts["button_r4"] = "cmd+shift+p"
    let data = try ProfileBuilder.build(
        baseData: JSONSerialization.data(withJSONObject: base),
        settings: settings
    )
    let root = try #require(JSONSerialization.jsonObject(with: data) as? [String: Any])
    let rules = try #require(root["rules"] as? [[String: Any]])
    let navigation = try #require(rules.first { $0["description"] as? String == ProfileBuilder.navigationDescription })
    let manipulators = try #require(navigation["manipulators"] as? [[String: Any]])
    let r4 = try #require(manipulators.first {
        ($0["from"] as? [String: Any])?["pointing_button"] as? String == "button6"
    })
    let to = try #require((r4["to"] as? [[String: Any]])?.first)
    #expect(to["key_code"] as? String == "p")
    #expect(to["modifiers"] as? [String] == ["left_command", "left_shift"])
}
