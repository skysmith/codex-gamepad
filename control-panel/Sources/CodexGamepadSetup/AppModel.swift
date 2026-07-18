import AppKit
import AVFoundation
import Combine
import Foundation
import SwiftUI

@MainActor
final class AppModel: ObservableObject {
    @Published var settings: GamepadSettings
    @Published var status = SetupStatus()
    @Published var voices: [String] = []
    @Published var isWorking = false
    @Published var operationTitle = "Ready"
    @Published var operationDetail = ""
    @Published var showingError = false
    @Published var errorMessage = ""

    private let synthesizer = AVSpeechSynthesizer()

    init() {
        settings = SettingsStore.load()
        voices = Self.availableVoiceNames()
        if settings.systemVoice.isEmpty {
            settings.systemVoice = Self.defaultVoiceName() ?? voices.first ?? ""
        }
        refreshStatus()
    }

    func actionBinding(for input: ControllerInput) -> Binding<BindingAction> {
        Binding(
            get: { self.settings.action(for: input) },
            set: { self.settings.bindings[input.id] = $0.rawValue }
        )
    }

    func customShortcutBinding(for input: ControllerInput) -> Binding<String> {
        Binding(
            get: { self.settings.customShortcuts[input.id] ?? "" },
            set: { self.settings.customShortcuts[input.id] = $0 }
        )
    }

    func resetBindings() {
        settings.bindings = Dictionary(
            uniqueKeysWithValues: ControllerInput.all.map { ($0.id, $0.defaultAction.rawValue) }
        )
    }

    func refreshStatus() {
        Task {
            status = await Self.readStatus()
        }
    }

    func savePreferences() {
        do {
            try SettingsStore.save(settings)
            operationTitle = "Preferences saved"
            operationDetail = "Voice preferences will be used on the next controller press."
        } catch {
            present(error)
        }
    }

    func installOrRepair() {
        runInstallation(
            includeKokoro: settings.speechBackend == "kokoro" && !status.kokoroInstalled
        )
    }

    func installKokoro() {
        runInstallation(includeKokoro: true)
    }

    func previewVoice() {
        guard settings.speechBackend == "apple" else { return }
        synthesizer.stopSpeaking(at: .immediate)
        let utterance = AVSpeechUtterance(string: "Codex Gamepad is ready.")
        utterance.voice = AVSpeechSynthesisVoice.speechVoices().first {
            $0.name == settings.systemVoice
        }
        utterance.rate = min(
            AVSpeechUtteranceMaximumSpeechRate,
            max(
                AVSpeechUtteranceMinimumSpeechRate,
                AVSpeechUtteranceDefaultSpeechRate * Float(settings.systemRate) / 200
            )
        )
        synthesizer.speak(utterance)
    }

    func openKarabiner() {
        let url = URL(fileURLWithPath: "/Applications/Karabiner-Elements.app")
        if FileManager.default.fileExists(atPath: url.path) {
            NSWorkspace.shared.openApplication(at: url, configuration: .init())
        } else if let download = URL(string: "https://karabiner-elements.pqrs.org/") {
            NSWorkspace.shared.open(download)
        }
    }

    func openEventViewer() {
        let url = URL(fileURLWithPath: "/Applications/Karabiner-EventViewer.app")
        if FileManager.default.fileExists(atPath: url.path) {
            NSWorkspace.shared.openApplication(at: url, configuration: .init())
        } else {
            openKarabiner()
        }
    }

    private func runInstallation(includeKokoro: Bool) {
        guard !isWorking else { return }
        isWorking = true
        operationTitle = includeKokoro ? "Installing optional Kokoro voice…" : "Installing Codex Gamepad…"
        operationDetail = "This can take a few minutes on the first install."
        Task {
            do {
                let payload = try Self.payloadURL()
                let baseProfile = payload.appendingPathComponent("karabiner/codex-gamepad.json")
                let profileData = try ProfileBuilder.build(
                    baseData: Data(contentsOf: baseProfile),
                    settings: settings
                )
                var settingsToInstall = settings
                if includeKokoro && !status.kokoroInstalled {
                    settingsToInstall.speechBackend = "apple"
                }
                try SettingsStore.save(settingsToInstall)
                try SettingsStore.saveProfile(profileData)

                let installer = payload.appendingPathComponent("scripts/install-local.sh")
                let receiver = payload.appendingPathComponent("bin/codex-gamepad-receiver")
                let uv = payload.appendingPathComponent("bin/uv")
                var arguments = [
                    installer.path,
                    "--create-venv",
                    "--uv", uv.path,
                    "--receiver-binary", receiver.path,
                    "--profile", SettingsStore.profileURL.path,
                    "--enable-managed-rules",
                ]
                if includeKokoro { arguments.append("--with-kokoro") }
                let installResult = try await Self.execute(
                    executable: URL(fileURLWithPath: "/bin/bash"),
                    arguments: arguments
                )
                guard installResult.status == 0 else {
                    throw SetupError.toolFailed(Self.failureSummary("Installation failed", installResult.output))
                }

                if includeKokoro {
                    operationTitle = "Downloading Kokoro voice files…"
                    let downloader = payload.appendingPathComponent("scripts/download-models.sh")
                    let destination = FileManager.default.homeDirectoryForCurrentUser
                        .appendingPathComponent(".local/share/codex-gamepad/models")
                    let downloadResult = try await Self.execute(
                        executable: URL(fileURLWithPath: "/bin/bash"),
                        arguments: [downloader.path, destination.path]
                    )
                    guard downloadResult.status == 0 else {
                        throw SetupError.toolFailed(Self.failureSummary("Kokoro download failed", downloadResult.output))
                    }
                    settings.speechBackend = "kokoro"
                    try SettingsStore.save(settings)
                }

                operationTitle = includeKokoro ? "Kokoro is ready" : "Codex Gamepad is ready"
                status = await Self.readStatus()
                operationDetail = status.controllerConnected
                    ? "Open Codex and try the controller."
                    : "Connect the 8BitDo controller, then open Codex and try it."
            } catch {
                present(error)
            }
            isWorking = false
        }
    }

    private func present(_ error: Error) {
        errorMessage = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        showingError = true
        operationTitle = "Needs attention"
        operationDetail = errorMessage
    }

    nonisolated private static func payloadURL() throws -> URL {
        if let override = ProcessInfo.processInfo.environment["CODEX_GAMEPAD_PAYLOAD"] {
            return URL(fileURLWithPath: override, isDirectory: true)
        }
        guard let resources = Bundle.main.resourceURL else {
            throw SetupError.missingPayload("Resources/Payload")
        }
        let payload = resources.appendingPathComponent("Payload", isDirectory: true)
        guard FileManager.default.fileExists(atPath: payload.path) else {
            throw SetupError.missingPayload("Resources/Payload")
        }
        return payload
    }

    nonisolated private static func execute(executable: URL, arguments: [String]) async throws -> ToolResult {
        try await Task.detached(priority: .userInitiated) {
            let process = Process()
            let pipe = Pipe()
            process.executableURL = executable
            process.arguments = arguments
            process.standardOutput = pipe
            process.standardError = pipe
            var environment = ProcessInfo.processInfo.environment
            environment.removeValue(forKey: "CODEX_GAMEPAD_PYTHON")
            process.environment = environment
            try process.run()
            let data = pipe.fileHandleForReading.readDataToEndOfFile()
            process.waitUntilExit()
            let clipped = data.suffix(65_536)
            return ToolResult(
                status: process.terminationStatus,
                output: String(data: clipped, encoding: .utf8) ?? ""
            )
        }.value
    }

    nonisolated private static func readStatus() async -> SetupStatus {
        await Task.detached(priority: .utility) {
            let fileManager = FileManager.default
            let home = fileManager.homeDirectoryForCurrentUser
            var value = SetupStatus()
            value.codexInstalled = [
                URL(fileURLWithPath: "/Applications/Codex.app"),
                URL(fileURLWithPath: "/Applications/ChatGPT.app"),
                home.appendingPathComponent("Applications/Codex.app"),
            ].contains { Bundle(url: $0)?.bundleIdentifier == "com.openai.codex" }
            value.karabinerInstalled = fileManager.fileExists(atPath: "/Applications/Karabiner-Elements.app")
            value.karabinerInitialized = fileManager.fileExists(
                atPath: home.appendingPathComponent(".config/karabiner/karabiner.json").path
            )
            let prefix = home.appendingPathComponent(".local/share/codex-gamepad")
            value.runtimeInstalled = fileManager.fileExists(atPath: prefix.appendingPathComponent(".codex-gamepad-install").path)
            value.receiverInstalled = fileManager.isExecutableFile(atPath: prefix.appendingPathComponent("bin/codex-gamepad-receiver").path)
            value.kokoroInstalled = fileManager.fileExists(atPath: prefix.appendingPathComponent("models/kokoro-v1.0.onnx").path)
                && fileManager.fileExists(atPath: prefix.appendingPathComponent("models/voices-v1.0.bin").path)

            let cli = URL(fileURLWithPath: "/Library/Application Support/org.pqrs/Karabiner-Elements/bin/karabiner_cli")
            if fileManager.isExecutableFile(atPath: cli.path),
               let result = try? await execute(executable: cli, arguments: ["--list-connected-devices"]),
               result.status == 0,
               let data = result.output.data(using: .utf8),
               let devices = try? JSONSerialization.jsonObject(with: data) as? [[String: Any]] {
                value.controllerConnected = devices.contains { device in
                    let identifiers = device["device_identifiers"] as? [String: Any]
                        ?? device["identifiers"] as? [String: Any]
                    return identifiers?["vendor_id"] as? Int == 11720
                        && identifiers?["product_id"] as? Int == 12315
                }
            }
            return value
        }.value
    }

    nonisolated private static func failureSummary(_ title: String, _ output: String) -> String {
        let lines = output.split(separator: "\n").suffix(8).joined(separator: "\n")
        return lines.isEmpty ? title : "\(title):\n\(lines)"
    }

    private static func availableVoiceNames() -> [String] {
        Array(Set(AVSpeechSynthesisVoice.speechVoices().map(\.name)))
            .sorted { $0.localizedStandardCompare($1) == .orderedAscending }
    }

    private static func defaultVoiceName() -> String? {
        AVSpeechSynthesisVoice(language: Locale.current.identifier)?.name
            ?? AVSpeechSynthesisVoice(language: "en-US")?.name
    }
}
