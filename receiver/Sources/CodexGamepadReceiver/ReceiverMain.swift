import AppKit
import Darwin
import Foundation
import KarabinerElementsUserCommandReceiver

private let expectedCommand = "codex_speak_last_response"
private let expectedVersion = 1
private let codexBundleIdentifier = "com.openai.codex"

@MainActor
private func triggerSpeaker() {
    guard NSWorkspace.shared.frontmostApplication?.bundleIdentifier == codexBundleIdentifier else {
        return
    }

    let environment = ProcessInfo.processInfo.environment
    let speakerPath = environment["CODEX_GAMEPAD_SPEAKER"]
        ?? FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".local/bin/codex-speak-last").path
    guard speakerPath.hasPrefix("/"), FileManager.default.isExecutableFile(atPath: speakerPath) else {
        FileHandle.standardError.write(Data("Codex Gamepad speaker is not installed.\n".utf8))
        return
    }

    let process = Process()
    process.executableURL = URL(fileURLWithPath: speakerPath)
    // The receiver already performed the independent frontmost-app check with
    // NSWorkspace, which does not require System Events automation access.
    process.arguments = ["--background", "--toggle"]
    process.standardInput = FileHandle.nullDevice
    process.standardOutput = FileHandle.nullDevice
    process.standardError = FileHandle.nullDevice
    do {
        try process.run()
    } catch {
        FileHandle.standardError.write(Data("Could not start Codex Gamepad speaker.\n".utf8))
    }
}

private func isAllowedCommand(_ json: Any) -> Bool {
    guard
        let root = json as? [String: Any],
        root["command"] as? String == expectedCommand,
        root["version"] as? Int == expectedVersion
    else {
        return false
    }
    return true
}

private func terminationSignals() -> AsyncStream<Int32> {
    signal(SIGINT, SIG_IGN)
    signal(SIGTERM, SIG_IGN)
    return AsyncStream { continuation in
        let interrupt = DispatchSource.makeSignalSource(signal: SIGINT, queue: .main)
        let terminate = DispatchSource.makeSignalSource(signal: SIGTERM, queue: .main)
        interrupt.setEventHandler { continuation.yield(SIGINT) }
        terminate.setEventHandler { continuation.yield(SIGTERM) }
        continuation.onTermination = { _ in
            interrupt.cancel()
            terminate.cancel()
        }
        interrupt.resume()
        terminate.resume()
    }
}

@main
struct CodexGamepadReceiver {
    static func main() async {
        if CommandLine.arguments.contains("--self-test") {
            let accepted = isAllowedCommand([
                "command": expectedCommand,
                "version": expectedVersion,
            ])
            let rejectedWrappedPayload = !isAllowedCommand([
                "payload": ["command": expectedCommand, "version": expectedVersion]
            ])
            let modeWatcherPassed = controllerModeWatcherSelfTest()
            Foundation.exit(accepted && rejectedWrappedPayload && modeWatcherPassed ? 0 : 1)
        }

        let environment = ProcessInfo.processInfo.environment
        let endpointPath = environment["CODEX_GAMEPAD_ENDPOINT"]
            ?? FileManager.default.homeDirectoryForCurrentUser
                .appendingPathComponent("Library/Application Support/Codex Gamepad/user-command.sock").path
        let receiver = KEUserCommandReceiver(
            path: endpointPath,
            onJSON: { json in
                guard isAllowedCommand(json) else { return }
                Task { @MainActor in triggerSpeaker() }
            },
            onError: { _ in
                FileHandle.standardError.write(Data("Karabiner command receiver error.\n".utf8))
            }
        )

        do {
            try await receiver.start()
            let modeWatcher = await MainActor.run {
                ControllerModeWatcher.startFromEnvironmentIfEnabled()
            }
            for await _ in terminationSignals() {
                break
            }
            await MainActor.run {
                modeWatcher?.stopAndRestoreCodexProfile()
            }
            await receiver.stop()
        } catch {
            FileHandle.standardError.write(Data("Could not start Karabiner command receiver.\n".utf8))
            Foundation.exit(1)
        }
    }
}
