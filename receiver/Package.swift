// swift-tools-version: 6.0

import PackageDescription

let package = Package(
    name: "CodexGamepadReceiver",
    platforms: [.macOS(.v15)],
    products: [
        .executable(name: "codex-gamepad-receiver", targets: ["CodexGamepadReceiver"])
    ],
    dependencies: [
        .package(
            url: "https://github.com/pqrs-org/Karabiner-Elements-user-command-receiver.git",
            exact: "1.2.0"
        )
    ],
    targets: [
        .executableTarget(
            name: "CodexGamepadReceiver",
            dependencies: [
                .product(
                    name: "KarabinerElementsUserCommandReceiver",
                    package: "Karabiner-Elements-user-command-receiver"
                )
            ],
            linkerSettings: [.linkedFramework("AppKit")]
        )
    ]
)
