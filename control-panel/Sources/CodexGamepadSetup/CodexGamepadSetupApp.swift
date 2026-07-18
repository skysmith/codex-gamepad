import SwiftUI

@main
struct CodexGamepadSetupApp: App {
    @StateObject private var model = AppModel()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(model)
                .frame(minWidth: 780, minHeight: 640)
        }
        .windowResizability(.contentMinSize)
        .commands {
            CommandGroup(after: .appInfo) {
                Button("Refresh Status") {
                    model.refreshStatus()
                }
                .keyboardShortcut("r", modifiers: .command)
            }
        }
    }
}
