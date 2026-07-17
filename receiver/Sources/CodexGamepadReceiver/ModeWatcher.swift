import AppKit
import Darwin
import Dispatch
import Foundation

enum ControllerProfileMode: Equatable {
    case codex
    case game
}

struct ControllerModeClassifier {
    static let aresBundleIdentifier = "dev.ares.ares"
    static let chromeBundleIdentifier = "com.google.Chrome"
    static let luantiBundleIdentifier = "org.luanti.luanti"

    static func classify(
        bundleIdentifier: String?,
        arguments: [String],
        arcadeChromeMarker: String,
        livingForestMarker: String
    ) -> ControllerProfileMode {
        switch bundleIdentifier {
        case aresBundleIdentifier:
            return .game
        case chromeBundleIdentifier:
            return arguments.contains(arcadeChromeMarker) ? .game : .codex
        case luantiBundleIdentifier:
            guard !livingForestMarker.isEmpty else { return .codex }
            return arguments.contains(where: { $0.contains(livingForestMarker) }) ? .game : .codex
        default:
            return .codex
        }
    }
}

private struct ControllerModeWatcherConfiguration {
    let karabinerCLI: URL
    let codexProfile: String
    let gameProfile: String
    let arcadeChromeMarker: String
    let livingForestMarker: String

    static func fromEnvironment(_ environment: [String: String]) -> Self? {
        guard environment["CODEX_GAMEPAD_MODE_SWITCHING"] == "1" else {
            return nil
        }

        let home = FileManager.default.homeDirectoryForCurrentUser.path
        let cliPath = nonempty(environment["CODEX_GAMEPAD_KARABINER_CLI"])
            ?? "/Library/Application Support/org.pqrs/Karabiner-Elements/bin/karabiner_cli"
        let codexProfile = nonempty(environment["CODEX_GAMEPAD_CODEX_PROFILE"])
            ?? "Codex Controller"
        let gameProfile = nonempty(environment["CODEX_GAMEPAD_GAME_PROFILE"])
            ?? "Game Mode"
        let arcadeChromeMarker = nonempty(environment["CODEX_GAMEPAD_ARCADE_CHROME_MARKER"])
            ?? "--user-data-dir=\(home)/Library/Application Support/Codex Arcade/Chrome"
        let livingForestMarker = nonempty(environment["CODEX_GAMEPAD_LIVING_FOREST_MARKER"])
            ?? "\(home)/Library/Application Support/Living Forest/runtime/players/"

        return Self(
            karabinerCLI: URL(fileURLWithPath: cliPath),
            codexProfile: codexProfile,
            gameProfile: gameProfile,
            arcadeChromeMarker: arcadeChromeMarker,
            livingForestMarker: livingForestMarker
        )
    }

    private static func nonempty(_ value: String?) -> String? {
        guard let value, !value.isEmpty else { return nil }
        return value
    }
}

private struct CommandResult {
    let status: Int32
    let output: String
}

@MainActor
final class ControllerModeWatcher: NSObject {
    private static let retryInterval: TimeInterval = 2
    private static let cliExecutionTimeout: DispatchTimeInterval = .seconds(2)
    private static let cliTerminationTimeout: DispatchTimeInterval = .milliseconds(250)

    private let configuration: ControllerModeWatcherConfiguration
    private let workspace: NSWorkspace
    private var retryTimer: Timer?
    private var lastError: String?

    static func startFromEnvironmentIfEnabled() -> ControllerModeWatcher? {
        guard let configuration = ControllerModeWatcherConfiguration.fromEnvironment(
            ProcessInfo.processInfo.environment
        ) else {
            return nil
        }
        let watcher = ControllerModeWatcher(configuration: configuration)
        watcher.start()
        return watcher
    }

    private init(
        configuration: ControllerModeWatcherConfiguration,
        workspace: NSWorkspace = .shared
    ) {
        self.configuration = configuration
        self.workspace = workspace
        super.init()
    }

    private func start() {
        let center = workspace.notificationCenter
        center.addObserver(
            self,
            selector: #selector(workspaceStateChanged(_:)),
            name: NSWorkspace.didActivateApplicationNotification,
            object: nil
        )
        center.addObserver(
            self,
            selector: #selector(workspaceStateChanged(_:)),
            name: NSWorkspace.didWakeNotification,
            object: nil
        )

        reconcile()
    }

    func stopAndRestoreCodexProfile() {
        cancelRetry()
        workspace.notificationCenter.removeObserver(self)
        _ = selectProfileIfNeeded(configuration.codexProfile)
    }

    @objc private func workspaceStateChanged(_ notification: Notification) {
        reconcile()
    }

    @objc private func retryReconciliation(_ timer: Timer) {
        retryTimer = nil
        reconcile()
    }

    private func reconcile() {
        let application = workspace.frontmostApplication
        let bundleIdentifier = application?.bundleIdentifier
        let arguments: [String]
        if bundleIdentifier == ControllerModeClassifier.chromeBundleIdentifier
            || bundleIdentifier == ControllerModeClassifier.luantiBundleIdentifier
        {
            guard let application, let processArguments = processArguments(for: application.processIdentifier) else {
                scheduleRetry()
                return
            }
            arguments = processArguments
        } else {
            arguments = []
        }

        let mode = ControllerModeClassifier.classify(
            bundleIdentifier: bundleIdentifier,
            arguments: arguments,
            arcadeChromeMarker: configuration.arcadeChromeMarker,
            livingForestMarker: configuration.livingForestMarker
        )
        let desiredProfile = mode == .game
            ? configuration.gameProfile
            : configuration.codexProfile
        if selectProfileIfNeeded(desiredProfile) {
            cancelRetry()
        } else {
            scheduleRetry()
        }
    }

    private func scheduleRetry() {
        guard retryTimer == nil else { return }
        let timer = Timer(
            timeInterval: Self.retryInterval,
            target: self,
            selector: #selector(retryReconciliation(_:)),
            userInfo: nil,
            repeats: false
        )
        RunLoop.main.add(timer, forMode: .common)
        retryTimer = timer
    }

    private func cancelRetry() {
        retryTimer?.invalidate()
        retryTimer = nil
    }

    @discardableResult
    private func selectProfileIfNeeded(_ desiredProfile: String) -> Bool {
        guard FileManager.default.isExecutableFile(atPath: configuration.karabinerCLI.path) else {
            reportErrorOnce("Karabiner CLI is unavailable; controller profile switching will retry.")
            return false
        }

        let currentResult = runKarabinerCLI(["--silent", "--show-current-profile-name"])
        guard currentResult.status == 0 else {
            reportErrorOnce("Could not read the current Karabiner profile; controller profile switching will retry.")
            return false
        }
        let currentProfile = currentResult.output.trimmingCharacters(in: .whitespacesAndNewlines)
        guard currentProfile != desiredProfile else {
            lastError = nil
            return true
        }

        let selectionResult = runKarabinerCLI(["--silent", "--select-profile", desiredProfile])
        guard selectionResult.status == 0 else {
            reportErrorOnce("Could not select the requested Karabiner profile; controller profile switching will retry.")
            return false
        }
        lastError = nil
        return true
    }

    private func runKarabinerCLI(_ arguments: [String]) -> CommandResult {
        let process = Process()
        let output = Pipe()
        process.executableURL = configuration.karabinerCLI
        process.arguments = arguments
        process.standardInput = FileHandle.nullDevice
        process.standardOutput = output
        process.standardError = FileHandle.nullDevice
        let termination = DispatchSemaphore(value: 0)
        process.terminationHandler = { _ in termination.signal() }
        do {
            try process.run()
            let processIdentifier = process.processIdentifier
            guard termination.wait(timeout: .now() + Self.cliExecutionTimeout) == .success else {
                process.terminate()
                if termination.wait(timeout: .now() + Self.cliTerminationTimeout) == .timedOut {
                    if processIdentifier > 0 {
                        kill(processIdentifier, SIGKILL)
                    }
                    _ = termination.wait(timeout: .now() + Self.cliTerminationTimeout)
                }
                return CommandResult(status: -1, output: "")
            }
            let data = output.fileHandleForReading.readDataToEndOfFile()
            return CommandResult(
                status: process.terminationStatus,
                output: String(decoding: data, as: UTF8.self)
            )
        } catch {
            return CommandResult(status: -1, output: "")
        }
    }

    private func reportErrorOnce(_ message: String) {
        guard lastError != message else { return }
        lastError = message
        FileHandle.standardError.write(Data("\(message)\n".utf8))
    }
}

private func processArguments(for pid: pid_t) -> [String]? {
    var query = [CTL_KERN, KERN_PROCARGS2, pid]
    var size = 0
    guard sysctl(&query, u_int(query.count), nil, &size, nil, 0) == 0, size > 0 else {
        return nil
    }

    var buffer = [UInt8](repeating: 0, count: size)
    let status = buffer.withUnsafeMutableBytes { bytes in
        sysctl(&query, u_int(query.count), bytes.baseAddress, &size, nil, 0)
    }
    guard status == 0 else {
        return nil
    }
    return parseKernProcArguments(Array(buffer.prefix(size)))
}

private func parseKernProcArguments(_ buffer: [UInt8]) -> [String]? {
    guard buffer.count >= MemoryLayout<Int32>.size else { return nil }
    let argumentCount = buffer.withUnsafeBytes { bytes in
        bytes.loadUnaligned(as: Int32.self)
    }
    guard argumentCount >= 0 else { return nil }
    if argumentCount == 0 { return [] }

    var offset = MemoryLayout<Int32>.size
    while offset < buffer.count, buffer[offset] != 0 {
        offset += 1
    }
    guard offset < buffer.count else { return nil }
    offset += 1
    while offset < buffer.count, buffer[offset] == 0 {
        offset += 1
    }
    guard Int(argumentCount) <= buffer.count - offset else { return nil }

    var arguments: [String] = []
    arguments.reserveCapacity(Int(argumentCount))
    for _ in 0..<Int(argumentCount) {
        guard offset < buffer.count else { return nil }
        let start = offset
        while offset < buffer.count, buffer[offset] != 0 {
            offset += 1
        }
        guard offset < buffer.count else { return nil }
        arguments.append(String(decoding: buffer[start..<offset], as: UTF8.self))
        offset += 1
    }
    return arguments
}

func controllerModeWatcherSelfTest() -> Bool {
    let arcadeMarker = "--user-data-dir=/Users/test/Library/Application Support/Codex Arcade/Chrome"
    let livingForestMarker = "/Users/test/Library/Application Support/Living Forest/runtime/players/"
    let classify: (String?, [String]) -> ControllerProfileMode = { bundleIdentifier, arguments in
        ControllerModeClassifier.classify(
            bundleIdentifier: bundleIdentifier,
            arguments: arguments,
            arcadeChromeMarker: arcadeMarker,
            livingForestMarker: livingForestMarker
        )
    }

    var rawArgumentCount: Int32 = 3
    var processBuffer = withUnsafeBytes(of: &rawArgumentCount) { Array($0) }
    func appendCString(_ value: String) {
        processBuffer.append(contentsOf: value.utf8)
        processBuffer.append(0)
    }
    appendCString("/usr/bin/arcade-test")
    processBuffer.append(contentsOf: [0, 0])
    appendCString("arcade-test")
    appendCString("")
    appendCString("--controller")
    appendCString("PRIVATE_ENVIRONMENT_VALUE=must-not-be-argv")
    let parsedArguments = parseKernProcArguments(processBuffer)

    return parsedArguments == ["arcade-test", "", "--controller"]
        && classify(ControllerModeClassifier.aresBundleIdentifier, []) == .game
        && classify(ControllerModeClassifier.chromeBundleIdentifier, [arcadeMarker]) == .game
        && classify(
            ControllerModeClassifier.chromeBundleIdentifier,
            ["--user-data-dir=/Users/test/Library/Application Support/Google/Chrome"]
        ) == .codex
        && classify(
            ControllerModeClassifier.chromeBundleIdentifier,
            ["prefix\(arcadeMarker)suffix"]
        ) == .codex
        && classify(
            ControllerModeClassifier.luantiBundleIdentifier,
            ["--config", "\(livingForestMarker)p1/client.conf"]
        ) == .game
        && classify(
            ControllerModeClassifier.luantiBundleIdentifier,
            ["--config", "/Users/test/Library/Application Support/Luanti/client.conf"]
        ) == .codex
        && classify("com.openai.codex", [arcadeMarker, livingForestMarker]) == .codex
        && classify(nil, []) == .codex
}
