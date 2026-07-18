import SwiftUI

struct ContentView: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        TabView {
            SetupView()
                .tabItem { Label("Setup", systemImage: "gamecontroller.fill") }
            ControlsView()
                .tabItem { Label("Controls", systemImage: "slider.horizontal.3") }
            VoiceView()
                .tabItem { Label("Voice", systemImage: "speaker.wave.2.fill") }
            AboutView()
                .tabItem { Label("About", systemImage: "info.circle") }
        }
        .padding(22)
        .alert("Codex Gamepad Setup", isPresented: $model.showingError) {
            Button("OK", role: .cancel) {}
        } message: {
            Text(model.errorMessage)
        }
    }
}

private struct SetupView: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            VStack(alignment: .leading, spacing: 6) {
                Text("Codex Gamepad")
                    .font(.largeTitle.bold())
                Text("Set up an 8BitDo Ultimate 2C as a focused controller for Codex.")
                    .foregroundStyle(.secondary)
            }

            GroupBox("Readiness") {
                Grid(alignment: .leading, horizontalSpacing: 28, verticalSpacing: 12) {
                    StatusRow(label: "Codex", ready: model.status.codexInstalled, readyText: "Installed", missingText: "Not found")
                    StatusRow(label: "Karabiner-Elements", ready: model.status.karabinerInstalled, readyText: "Installed", missingText: "Required")
                    StatusRow(label: "Karabiner configuration", ready: model.status.karabinerInitialized, readyText: "Ready", missingText: "Open Karabiner once")
                    StatusRow(label: "Codex Gamepad runtime", ready: model.status.runtimeInstalled && model.status.receiverInstalled, readyText: "Installed", missingText: "Not installed")
                    StatusRow(label: "8BitDo Ultimate 2C", ready: model.status.controllerConnected, readyText: "Connected", missingText: "Not detected")
                }
                .padding(8)
            }

            HStack(spacing: 12) {
                Button(model.status.runtimeInstalled ? "Repair / Update" : "Install") {
                    model.installOrRepair()
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .disabled(
                    model.isWorking
                        || !model.status.karabinerInstalled
                        || !model.status.karabinerInitialized
                )

                Button(model.status.karabinerInstalled ? "Open Karabiner" : "Get Karabiner") {
                    model.openKarabiner()
                }
                .controlSize(.large)

                Button("Refresh") { model.refreshStatus() }
                    .controlSize(.large)
                    .disabled(model.isWorking)
            }

            if !model.status.karabinerInitialized {
                Label(
                    "Install and open Karabiner-Elements once, approve its macOS permissions, then return here.",
                    systemImage: "exclamationmark.triangle.fill"
                )
                .foregroundStyle(.orange)
            }

            GroupBox {
                HStack(spacing: 12) {
                    if model.isWorking { ProgressView().controlSize(.small) }
                    VStack(alignment: .leading, spacing: 3) {
                        Text(model.operationTitle).font(.headline)
                        if !model.operationDetail.isEmpty {
                            Text(model.operationDetail).font(.callout).foregroundStyle(.secondary)
                        }
                    }
                    Spacer()
                }
                .padding(6)
            }
            Spacer()
        }
    }
}

private struct StatusRow: View {
    let label: String
    let ready: Bool
    let readyText: String
    let missingText: String

    var body: some View {
        GridRow {
            Label(label, systemImage: ready ? "checkmark.circle.fill" : "circle.dashed")
                .foregroundStyle(ready ? .green : .secondary)
            Text(ready ? readyText : missingText)
                .foregroundStyle(.secondary)
        }
    }
}

private struct ControlsView: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Controller bindings").font(.title.bold())
            Text("Mappings are restricted to the verified Ultimate 2C and only fire while Codex is frontmost.")
                .foregroundStyle(.secondary)

            ScrollView {
                Grid(alignment: .leading, horizontalSpacing: 24, verticalSpacing: 10) {
                    GridRow {
                        Text("Controller input").font(.headline)
                        Text("Codex action").font(.headline)
                        Text("Shortcut").font(.headline)
                    }
                    Divider().gridCellColumns(3)
                    ForEach(ControllerInput.all) { input in
                        GridRow {
                            Text(input.label).frame(minWidth: 120, alignment: .leading)
                            Picker("", selection: model.actionBinding(for: input)) {
                                ForEach(BindingAction.allCases) { action in
                                    Text(action.label).tag(action)
                                }
                            }
                            .labelsHidden()
                            .frame(minWidth: 300)
                            if model.settings.action(for: input) == .custom {
                                TextField("cmd+shift+p", text: model.customShortcutBinding(for: input))
                                    .textFieldStyle(.roundedBorder)
                                    .frame(minWidth: 150)
                            } else {
                                Text("—").foregroundStyle(.tertiary)
                            }
                        }
                    }
                }
                .padding(.vertical, 6)
            }

            HStack {
                Button("Apply Bindings") { model.installOrRepair() }
                    .buttonStyle(.borderedProminent)
                    .disabled(
                        model.isWorking
                            || !model.status.karabinerInstalled
                            || !model.status.karabinerInitialized
                    )
                Button("Restore Defaults") { model.resetBindings() }
                Spacer()
                Text("Custom syntax: cmd+shift+p. Keep at least one Speak / Stop binding.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
    }
}

private struct VoiceView: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            Text("Voice").font(.title.bold())
            Text("Speech stays on this Mac. Apple voices require no download; Kokoro is an optional quality upgrade.")
                .foregroundStyle(.secondary)

            Picker("Speech engine", selection: $model.settings.speechBackend) {
                Text("Apple — Built in").tag("apple")
                Text("Kokoro — Optional").tag("kokoro")
            }
            .pickerStyle(.segmented)

            if model.settings.speechBackend == "apple" {
                Form {
                    Picker("Voice", selection: $model.settings.systemVoice) {
                        ForEach(model.voices, id: \.self) { Text($0).tag($0) }
                    }
                    HStack {
                        Slider(
                            value: Binding(
                                get: { Double(model.settings.systemRate) },
                                set: { model.settings.systemRate = Int($0) }
                            ),
                            in: 120...360,
                            step: 5
                        )
                        Text("\(model.settings.systemRate) wpm").monospacedDigit().frame(width: 74)
                    }
                }
                HStack {
                    Button("Preview") { model.previewVoice() }
                    Button("Save Voice") { model.savePreferences() }
                        .buttonStyle(.borderedProminent)
                }
            } else {
                GroupBox {
                    VStack(alignment: .leading, spacing: 12) {
                        Label(
                            model.status.kokoroInstalled ? "Kokoro model files are installed." : "Kokoro is not bundled with this app.",
                            systemImage: model.status.kokoroInstalled ? "checkmark.circle.fill" : "arrow.down.circle"
                        )
                        Text("Installing Kokoro downloads its Python packages and model files from their upstream projects. You can switch back to Apple voices at any time.")
                            .foregroundStyle(.secondary)
                        HStack {
                            TextField("Voice", text: $model.settings.kokoroVoice).frame(width: 160)
                            Slider(value: $model.settings.kokoroSpeed, in: 0.7...1.4, step: 0.05)
                            Text(String(format: "%.2f×", model.settings.kokoroSpeed)).monospacedDigit()
                        }
                        HStack {
                            Button(model.status.kokoroInstalled ? "Repair Kokoro" : "Install Kokoro") {
                                model.installKokoro()
                            }
                            .buttonStyle(.borderedProminent)
                            .disabled(
                                model.isWorking
                                    || !model.status.karabinerInstalled
                                    || !model.status.karabinerInitialized
                            )
                            Link("About Kokoro", destination: URL(string: "https://huggingface.co/hexgrad/Kokoro-82M")!)
                        }
                    }
                    .padding(6)
                }
            }
            Spacer()
        }
    }
}

private struct AboutView: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text("Test and support").font(.title.bold())
            GroupBox("Hardware test") {
                VStack(alignment: .leading, spacing: 10) {
                    Text("Open EventViewer, select Devices, and confirm the controller appears as an 8BitDo Ultimate 2C. Then test each mapped input while Codex is frontmost.")
                    Button("Open Karabiner EventViewer") { model.openEventViewer() }
                }
                .padding(6)
            }
            GroupBox("Privacy and scope") {
                Text("Codex response text is read locally from Codex, cleaned in memory, and sent to the selected local voice. Apple speech receives text over stdin so it is not exposed in process arguments. Controller mappings are limited to the verified device IDs and the Codex bundle ID.")
                    .padding(6)
            }
            HStack(spacing: 16) {
                Link("Project on GitHub", destination: URL(string: "https://github.com/skysmith/codex-gamepad")!)
                Link("Report an issue", destination: URL(string: "https://github.com/skysmith/codex-gamepad/issues")!)
                Spacer()
                Text("Apple Silicon · macOS 15+").foregroundStyle(.secondary)
            }
            Spacer()
        }
    }
}
