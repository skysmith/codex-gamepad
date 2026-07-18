// swift-tools-version: 6.0

import PackageDescription

let package = Package(
    name: "CodexGamepadSetup",
    platforms: [.macOS(.v15)],
    products: [
        .executable(name: "CodexGamepadSetup", targets: ["CodexGamepadSetup"])
    ],
    targets: [
        .executableTarget(
            name: "CodexGamepadSetup",
            linkerSettings: [
                .linkedFramework("AppKit"),
                .linkedFramework("AVFoundation"),
                .linkedFramework("SwiftUI"),
            ]
        ),
        .testTarget(
            name: "CodexGamepadSetupTests",
            dependencies: ["CodexGamepadSetup"]
        ),
    ]
)
