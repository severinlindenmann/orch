import XCTest

/// Evidence screenshots of the conversation screens (default and XXL text) for the PR. Runs only when the target folder exists.
final class ConversationShotsUITests: XCTestCase {
    private var dir: URL!
    override func setUpWithError() throws {
        continueAfterFailure = false
        let home = ProcessInfo.processInfo.environment["SIMULATOR_HOST_HOME"] ?? NSHomeDirectory()
        dir = URL(fileURLWithPath: home).appendingPathComponent("orch-dev/state/mobile-v3-messenger/build/shots/m2/app")
        try XCTSkipUnless(FileManager.default.fileExists(atPath: dir.path), "no shots folder")
    }
    private func launch(_ extra: [String], size: String?) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES", "-fakeVoice", "YES", "-undoSeconds", "60"] + extra
        if let size { app.launchArguments += ["-UIPreferredContentSizeCategoryName", size] }
        app.launch()
        return app
    }
    private func shot(_ app: XCUIApplication, _ name: String) throws {
        sleep(2)
        try app.screenshot().pngRepresentation.write(to: dir.appendingPathComponent("\(name).png"))
    }
    private func el(_ app: XCUIApplication, _ id: String) -> XCUIElement { app.descendants(matching: .any)[id].firstMatch }

    func testShots() throws {
        for (suffix, size) in [("", nil), ("-xxl", "UICTContentSizeCategoryXXL")] as [(String, String?)] {
            // General with a started chip and a voice note
            var app = launch(["-openChat", "ws_pilatus001"], size: size)
            let general = app.buttons["general-ws_pilatus001"]; if general.waitForExistence(timeout: 15) { general.tap() }
            let field = el(app, "composer-field"); XCTAssertTrue(field.waitForExistence(timeout: 15))
            field.tap(); field.typeText("Start the board summary"); el(app, "composer-send").tap()
            _ = app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH 'started-chip-'")).firstMatch.waitForExistence(timeout: 10)
            try shot(app, "general\(suffix)"); app.terminate()

            // Topic chat with questions
            app = launch(["-openChat", "ws_pilatus001", "-openTicket", "t_7k3f9q"], size: size)
            XCTAssertTrue(el(app, "answer-TIMESTAMP").waitForExistence(timeout: 15))
            try shot(app, "topic-questions\(suffix)")
            el(app, "answer-TIMESTAMP").tap()
            _ = app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH 'undo-'")).firstMatch.waitForExistence(timeout: 5)
            try shot(app, "question-undo\(suffix)")

            // Recording: drag up from the mic = locked hands-free row
            let mic = el(app, "composer-mic"); XCTAssertTrue(mic.waitForExistence(timeout: 10))
            let start = mic.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5))
            start.press(forDuration: 0.6, thenDragTo: start.withOffset(CGVector(dx: 0, dy: -110)))
            _ = el(app, "rec-send").waitForExistence(timeout: 5)
            try shot(app, "recording\(suffix)"); app.terminate()
        }
    }
}
