import CryptoKit
import XCTest

/// ORCH-1296: real pushes through the notification extension in the Simulator. Needs an outside `xcrun simctl push`,
/// so it runs only from mobile/scripts/signed-push-check.sh (`ORCH_SIGNED_PUSH_DIR` set). The script pushes
/// `<name>.json` when the test writes `<name>.ready` into that folder; screenshots land there as `<name>.png`.
final class SignedPushUITests: XCTestCase {
    override func setUp() { continueAfterFailure = false }

    func testOnlySignedWordsShowInAPush() throws {
        let dir = ProcessInfo.processInfo.environment["ORCH_SIGNED_PUSH_DIR"] ?? ""
        try XCTSkipIf(dir.isEmpty, "needs scripts/signed-push-check.sh")
        // The fixed TEST key of scripts/signed-push-gen.swift, accepted for the mock workspace on this Simulator.
        let key = try Curve25519.Signing.PrivateKey(rawRepresentation: Data(repeating: 7, count: 32))
        let pub = key.publicKey.rawRepresentation.base64EncodedString()
            .replacingOccurrences(of: "+", with: "-").replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "=", with: "")
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedNotify", "YES",
                                "-seedPushTrust", "ws_pilatus001:\(pub)", "-seedPushPhone", "ph_mock000000"]
        app.launch()
        let allow = app.buttons["Allow notifications"]
        XCTAssertTrue(allow.waitForExistence(timeout: 15))
        allow.tap()
        let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")
        if springboard.buttons["Allow"].waitForExistence(timeout: 5) { springboard.buttons["Allow"].tap() }
        XCTAssertTrue(app.buttons["room-ws_pilatus001"].waitForExistence(timeout: 15))
        XCUIDevice.shared.press(.home)

        for (name, expected, never) in [("signed", "Delete the old backups?", "Keep the old backups?"),
                                        ("changed", "New message from Pilatus Workspace", "Keep the old backups?"),
                                        ("unsigned", "New message from Pilatus Workspace", "Keep the old backups?")] {
            FileManager.default.createFile(atPath: "\(dir)/\(name).ready", contents: Data())
            let banner = springboard.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS %@", expected)).firstMatch
            _ = banner.waitForExistence(timeout: 20)
            XCTAssertTrue(banner.exists, "\(name): no banner with \(expected)")
            let shot = XCUIScreen.main.screenshot()
            try shot.pngRepresentation.write(to: URL(fileURLWithPath: "\(dir)/\(name).png"))
            let attachment = XCTAttachment(screenshot: shot)
            attachment.name = name
            attachment.lifetime = .keepAlways
            add(attachment)
            XCTAssertFalse(springboard.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS %@", never)).firstMatch.exists,
                           "\(name): the relay's own words showed")
            // Let the banner go before the next push.
            banner.swipeUp()
            sleep(2)
        }
    }
}
