import Darwin
import Foundation

enum SettingsStore {
    static let configURL = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent(".config/codex-gamepad/config.json")
    static let profileURL = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Library/Application Support/Codex Gamepad/custom-profile.json")

    static func load() -> GamepadSettings {
        guard let data = try? Data(contentsOf: configURL),
              let value = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { return GamepadSettings() }
        var settings = GamepadSettings()
        settings.speechBackend = value["speech_backend"] as? String ?? settings.speechBackend
        settings.systemVoice = value["system_voice"] as? String ?? settings.systemVoice
        settings.systemRate = value["system_rate"] as? Int ?? settings.systemRate
        settings.kokoroVoice = value["voice"] as? String ?? settings.kokoroVoice
        settings.kokoroSpeed = value["speed"] as? Double ?? settings.kokoroSpeed
        if let bindings = value["bindings"] as? [String: String] {
            settings.bindings.merge(bindings) { _, new in new }
        }
        settings.customShortcuts = value["custom_shortcuts"] as? [String: String] ?? [:]
        return settings
    }

    static func save(_ settings: GamepadSettings) throws {
        var value: [String: Any] = [:]
        if FileManager.default.fileExists(atPath: configURL.path) {
            try rejectSymbolicLink(configURL)
            let existing = try Data(contentsOf: configURL)
            value = (try JSONSerialization.jsonObject(with: existing) as? [String: Any]) ?? [:]
        }
        value["speech_backend"] = settings.speechBackend
        value["system_voice"] = settings.systemVoice
        value["system_rate"] = settings.systemRate
        value["voice"] = settings.kokoroVoice
        value["speed"] = settings.kokoroSpeed
        value["bindings"] = settings.bindings
        value["custom_shortcuts"] = settings.customShortcuts
        let data = try JSONSerialization.data(withJSONObject: value, options: [.prettyPrinted, .sortedKeys]) + Data([0x0a])
        try privateAtomicWrite(data, to: configURL)
    }

    static func saveProfile(_ data: Data) throws {
        if FileManager.default.fileExists(atPath: profileURL.path) {
            try rejectSymbolicLink(profileURL)
        }
        try privateAtomicWrite(data, to: profileURL)
    }

    private static func rejectSymbolicLink(_ url: URL) throws {
        let values = try url.resourceValues(forKeys: [.isSymbolicLinkKey, .isRegularFileKey])
        guard values.isSymbolicLink != true, values.isRegularFile == true else {
            throw SetupError.unsafePath(url.path)
        }
    }

    private static func privateAtomicWrite(_ data: Data, to destination: URL) throws {
        let directory = destination.deletingLastPathComponent()
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        _ = chmod(directory.path, 0o700)
        let temporary = directory.appendingPathComponent(".\(destination.lastPathComponent).\(UUID().uuidString).tmp")
        do {
            try data.write(to: temporary)
            guard chmod(temporary.path, 0o600) == 0 else {
                throw SetupError.unsafePath("could not protect \(destination.lastPathComponent)")
            }
            if FileManager.default.fileExists(atPath: destination.path) {
                _ = try FileManager.default.replaceItemAt(destination, withItemAt: temporary)
            } else {
                try FileManager.default.moveItem(at: temporary, to: destination)
            }
        } catch {
            try? FileManager.default.removeItem(at: temporary)
            throw error
        }
    }
}
