// swift-tools-version:5.10
import PackageDescription

let package = Package(
    name: "DipAgentX",
    platforms: [.macOS(.v14)],
    dependencies: [
        .package(path: "../shared/DipAgentXKit")
    ],
    targets: [
        .executableTarget(
            name: "DipAgentX",
            dependencies: [.product(name: "DipAgentXKit", package: "DipAgentXKit")],
            path: "Sources/DipAgentX"
        )
    ]
)
