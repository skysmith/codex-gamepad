import Foundation

struct ControllerInput: Identifiable, Hashable, Sendable {
    let id: String
    let label: String
    let eventKey: String
    let eventValue: String
    let defaultAction: BindingAction

    static let all: [ControllerInput] = [
        .init(id: "dpad_up", label: "D-pad Up", eventKey: "generic_desktop", eventValue: "dpad_up", defaultAction: .arrowUp),
        .init(id: "dpad_down", label: "D-pad Down", eventKey: "generic_desktop", eventValue: "dpad_down", defaultAction: .arrowDown),
        .init(id: "dpad_left", label: "D-pad Left", eventKey: "generic_desktop", eventValue: "dpad_left", defaultAction: .arrowLeft),
        .init(id: "dpad_right", label: "D-pad Right", eventKey: "generic_desktop", eventValue: "dpad_right", defaultAction: .arrowRight),
        .init(id: "button_a", label: "A", eventKey: "pointing_button", eventValue: "button1", defaultAction: .dictate),
        .init(id: "button_b", label: "B", eventKey: "pointing_button", eventValue: "button2", defaultAction: .escape),
        .init(id: "button_x", label: "X", eventKey: "pointing_button", eventValue: "button4", defaultAction: .speak),
        .init(id: "button_y", label: "Y", eventKey: "pointing_button", eventValue: "button5", defaultAction: .tab),
        .init(id: "button_lb", label: "LB", eventKey: "pointing_button", eventValue: "button7", defaultAction: .previousTask),
        .init(id: "button_rb", label: "RB", eventKey: "pointing_button", eventValue: "button8", defaultAction: .nextTask),
        .init(id: "button_l4", label: "L4", eventKey: "pointing_button", eventValue: "button3", defaultAction: .commandMenu),
        .init(id: "button_r4", label: "R4", eventKey: "pointing_button", eventValue: "button6", defaultAction: .unmapped),
        .init(id: "button_rt", label: "RT", eventKey: "pointing_button", eventValue: "button10", defaultAction: .send),
    ]
}

enum BindingAction: String, CaseIterable, Identifiable, Sendable {
    case arrowUp = "arrow_up"
    case arrowDown = "arrow_down"
    case arrowLeft = "arrow_left"
    case arrowRight = "arrow_right"
    case dictate
    case escape
    case speak
    case tab
    case commandMenu = "command_menu"
    case previousTask = "previous_task"
    case nextTask = "next_task"
    case send
    case space
    case deleteBackward = "delete_backward"
    case pageUp = "page_up"
    case pageDown = "page_down"
    case custom
    case unmapped

    var id: String { rawValue }

    var label: String {
        switch self {
        case .arrowUp: "Up Arrow"
        case .arrowDown: "Down Arrow"
        case .arrowLeft: "Left Arrow"
        case .arrowRight: "Right Arrow"
        case .dictate: "Dictate (⌃⇧D)"
        case .escape: "Cancel (Esc)"
        case .speak: "Speak / Stop"
        case .tab: "Next Field (Tab)"
        case .commandMenu: "Command Menu (⌘K)"
        case .previousTask: "Previous Task (⌘⇧[)"
        case .nextTask: "Next Task (⌘⇧])"
        case .send: "Send (Return)"
        case .space: "Space"
        case .deleteBackward: "Delete"
        case .pageUp: "Page Up"
        case .pageDown: "Page Down"
        case .custom: "Custom Shortcut…"
        case .unmapped: "Unmapped"
        }
    }
}

struct GamepadSettings: Sendable {
    var speechBackend = "apple"
    var systemVoice = ""
    var systemRate = 200
    var kokoroVoice = "af_heart"
    var kokoroSpeed = 1.05
    var bindings: [String: String] = Dictionary(
        uniqueKeysWithValues: ControllerInput.all.map { ($0.id, $0.defaultAction.rawValue) }
    )
    var customShortcuts: [String: String] = [:]

    func action(for input: ControllerInput) -> BindingAction {
        BindingAction(rawValue: bindings[input.id] ?? "") ?? input.defaultAction
    }
}

struct SetupStatus: Sendable {
    var codexInstalled = false
    var karabinerInstalled = false
    var karabinerInitialized = false
    var runtimeInstalled = false
    var receiverInstalled = false
    var controllerConnected = false
    var kokoroInstalled = false

    var ready: Bool {
        codexInstalled && karabinerInstalled && karabinerInitialized
            && runtimeInstalled && receiverInstalled
    }
}

struct ToolResult: Sendable {
    let status: Int32
    let output: String
}

enum SetupError: LocalizedError {
    case missingPayload(String)
    case invalidProfile(String)
    case unsafePath(String)
    case toolFailed(String)

    var errorDescription: String? {
        switch self {
        case .missingPayload(let item): "The setup payload is missing \(item)."
        case .invalidProfile(let reason): "The controller profile is invalid: \(reason)"
        case .unsafePath(let reason): "A settings path is unsafe: \(reason)"
        case .toolFailed(let reason): reason
        }
    }
}
