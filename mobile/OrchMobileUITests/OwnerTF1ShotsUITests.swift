import XCTest

/// Evidence screenshots of the owner TestFlight round 1 fixes (default and XXL text). Runs only when the target folder exists.
final class OwnerTF1ShotsUITests: XCTestCase {
    private var dir: URL!
    override func setUpWithError() throws {
        continueAfterFailure = false
        let home = ProcessInfo.processInfo.environment["SIMULATOR_HOST_HOME"] ?? NSHomeDirectory()
        dir = URL(fileURLWithPath: home).appendingPathComponent("orch-dev/state/mobile-v3-messenger/build/shots/w8/app")
        try XCTSkipUnless(FileManager.default.fileExists(atPath: dir.path), "no shots folder")
    }
    private func launch(_ extra: [String], size: String?) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES", "-undoSeconds", "60"] + extra
        if let size { app.launchArguments += ["-UIPreferredContentSizeCategoryName", size] }
        app.launch()
        return app
    }
    private func shot(_ app: XCUIApplication, _ name: String) throws {
        sleep(2)
        try app.screenshot().pngRepresentation.write(to: dir.appendingPathComponent("\(name).png"))
    }

    func testShots() throws {
        for (suffix, size) in [("", nil), ("-xxl", "UICTContentSizeCategoryXXL")] as [(String, String?)] {
            var app = launch([], size: size)
            XCTAssertTrue(app.buttons["room-ws_pilatus001"].waitForExistence(timeout: 15))
            try shot(app, "chats\(suffix)")
            if size == nil {   // the XXL settings list crashes the XCUITest runner on swipe; default size only
                app.buttons["settings-button"].tap()
                let voice = app.buttons["voice-settings"]
                XCTAssertTrue(voice.waitForExistence(timeout: 10))
                for _ in 0..<6 { if voice.isHittable { break }; app.swipeUp() }
                try shot(app, "settings\(suffix)")
                voice.coordinate(withNormalizedOffset: CGVector(dx: 0.6, dy: 0.5)).tap()
                XCTAssertTrue(app.navigationBars["Voice"].waitForExistence(timeout: 5))
                try shot(app, "voice-settings\(suffix)")
            }
            app.terminate()

            app = launch(["-openChat", "ws_pilatus001", "-fakeLocation", "YES"], size: size)
            let general = app.buttons["general-ws_pilatus001"]; XCTAssertTrue(general.waitForExistence(timeout: 20)); general.tap()
            let field = app.descendants(matching: .any)["composer-field"].firstMatch
            XCTAssertTrue(field.waitForExistence(timeout: 15))
            try shot(app, "chat-top\(suffix)")
            field.tap(); try shot(app, "chat-keyboard\(suffix)")
            app.descendants(matching: .any)["composer-attach"].firstMatch.tap()
            XCTAssertTrue(app.buttons["media-location"].waitForExistence(timeout: 5))
            try shot(app, "share-sheet\(suffix)")
            app.buttons["media-location"].tap()
            XCTAssertTrue(app.buttons["Open in Maps"].waitForExistence(timeout: 10))
            try shot(app, "location-sheet\(suffix)")
            app.buttons["media-send"].tap()
            XCTAssertTrue(app.buttons["Open in Maps"].waitForExistence(timeout: 15))
            try shot(app, "location-card\(suffix)")
            app.terminate()
        }
    }
}
