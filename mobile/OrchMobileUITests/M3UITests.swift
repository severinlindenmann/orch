import XCTest

/// M3 flows against the mock relay, hosted by `M3DemoHost` (debug): artifact viewer, comment pins, media picker, conversation info.
@MainActor final class M3UITests: XCTestCase {
    private func launch(_ mode: String, extra: [String] = []) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES", "-m3Host", mode] + extra
        app.launch()
        return app
    }
    private func feedbackCount(_ app: XCUIApplication) -> String { app.staticTexts["demo-feedback-count"].label }
    /// Evidence for the PR; only when the shots folder exists.
    private func shot(_ app: XCUIApplication, _ name: String) {
        let home = ProcessInfo.processInfo.environment["SIMULATOR_HOST_HOME"] ?? NSHomeDirectory()
        let dir = URL(fileURLWithPath: home).appendingPathComponent("orch-dev/state/mobile-v3-messenger/build/shots/info-tabs")
        guard FileManager.default.fileExists(atPath: dir.path) else { return }
        try? app.screenshot().pngRepresentation.write(to: dir.appendingPathComponent("\(name).png"))
    }

    func testLooksGoodOnAPageSendsApproveFeedback() throws {
        let app = launch("viewer-html")
        XCTAssertTrue(app.buttons["artifact-looks-good"].waitForExistence(timeout: 20))
        XCTAssertTrue(app.webViews.firstMatch.waitForExistence(timeout: 10))
        let good = app.buttons["artifact-looks-good"]
        XCTAssertTrue(app.webViews.firstMatch.waitForExistence(timeout: 10))
        let enabled = NSPredicate(format: "isEnabled == true")
        wait(for: [XCTNSPredicateExpectation(predicate: enabled, object: good)], timeout: 10)   // enabled only once the page is shown
        good.tap()
        XCTAssertTrue(app.staticTexts["demo-feedback-count"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.staticTexts["feedback sent: 1"].waitForExistence(timeout: 10))
        XCTAssertFalse(app.buttons["artifact-close"].exists, "the viewer closes after sending")
    }

    func testHTMLCommentPinsAreSentAsChanges() throws {
        let app = launch("viewer-html")
        XCTAssertTrue(app.buttons["artifact-comment"].waitForExistence(timeout: 20))
        sleep(2)   // the page is decrypted and loaded
        app.buttons["artifact-comment"].tap()
        XCTAssertTrue(app.buttons["artifact-send-comments"].exists)
        XCTAssertFalse(app.buttons["artifact-send-comments"].isEnabled, "no pin yet")
        app.webViews.firstMatch.coordinate(withNormalizedOffset: CGVector(dx: 0.4, dy: 0.2)).tap()
        let text = app.textViews["pin-text"].firstMatch.exists ? app.textViews["pin-text"] : app.textFields["pin-text"]
        XCTAssertTrue(text.waitForExistence(timeout: 10))
        text.tap(); text.typeText("Make this heading shorter")
        app.buttons["pin-save"].tap()
        XCTAssertTrue(app.buttons["pin-chip-1"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["artifact-send-comments"].isEnabled)
        app.buttons["artifact-send-comments"].tap()
        XCTAssertTrue(app.staticTexts["feedback sent: 1"].waitForExistence(timeout: 10))
    }

    func testPDFPinIsPlacedAndEdited() throws {
        let app = launch("viewer-pdf")
        XCTAssertTrue(app.buttons["artifact-comment"].waitForExistence(timeout: 20))
        sleep(1)
        app.buttons["artifact-comment"].tap()
        app.buttons["artifact-add-pin"].tap()   // the no-tap way (VoiceOver): a pin in the middle of the page
        let text = app.textViews["pin-text"].firstMatch.exists ? app.textViews["pin-text"] : app.textFields["pin-text"]
        XCTAssertTrue(text.waitForExistence(timeout: 10))
        text.tap(); text.typeText("Fix the title")
        app.buttons["pin-save"].tap()
        XCTAssertTrue(app.buttons["pin-chip-1"].waitForExistence(timeout: 5))
        // delete through the chip's x
        app.buttons["pin-chip-delete-1"].tap()
        XCTAssertFalse(app.buttons["pin-chip-1"].exists)
        XCTAssertFalse(app.buttons["artifact-send-comments"].isEnabled)
        app.buttons["artifact-cancel-comments"].tap()
        XCTAssertTrue(app.buttons["artifact-comment"].exists)
    }

    func testImageViewerLooksGood() throws {
        let app = launch("viewer-image")
        XCTAssertTrue(app.buttons["artifact-looks-good"].waitForExistence(timeout: 20))
        let good = app.buttons["artifact-looks-good"]
        wait(for: [XCTNSPredicateExpectation(predicate: NSPredicate(format: "isEnabled == true"), object: good)], timeout: 10)
        good.tap()
        XCTAssertTrue(app.staticTexts["feedback sent: 1"].waitForExistence(timeout: 10))
    }

    func testMediaPickerOffersTheFourSources() throws {
        let app = launch("picker")
        // Camera is hidden when the device has none (Simulator): Photos, Files and Location always show.
        for id in ["media-photos", "media-files", "media-location"] {
            XCTAssertTrue(app.buttons[id].waitForExistence(timeout: 20), id)
        }
        app.buttons["media-close"].tap()
        XCTAssertTrue(app.buttons["demo-open-picker"].waitForExistence(timeout: 5))
    }

    /// TF 10 + 14: the four tabs sit in one row (one line each, also with large text) and the voice row is gone
    /// (Settings > Voice holds Swiss German; replies follow the language the person spoke).
    func testConversationInfoTabsOneLineNoLanguageRow() throws {
        for size in ["", "UICTContentSizeCategoryAccessibilityXXL"] {
            let app = launch("info", extra: size.isEmpty ? [] : ["-UIPreferredContentSizeCategoryName", size])
            XCTAssertTrue(app.buttons["demo-open-info"].waitForExistence(timeout: 20))
            app.buttons["demo-open-info"].tap()
            // P33: only filters with content are shown; the Q3 demo has a photo, a file and links (Previews only if present)
            let photos = app.buttons["info-tab-photos"]
            XCTAssertTrue(photos.waitForExistence(timeout: 10))
            for t in ["photos", "files", "links"] { XCTAssertTrue(app.buttons["info-tab-\(t)"].exists, "\(t) filter missing (\(size))") }
            for t in ["photos", "files", "links", "artifacts"] {
                let tab = app.buttons["info-tab-\(t)"]
                guard t != "artifacts" || tab.exists else { continue }
                // one line: every tab is as tall as Photos, and all sit in the same row
                XCTAssertEqual(tab.frame.height, photos.frame.height, accuracy: 1, "\(t) wraps (\(size))")
                XCTAssertEqual(tab.frame.midY, photos.frame.midY, accuracy: 1, "\(t) not in one row (\(size))")
            }
            XCTAssertFalse(app.buttons["info-language-row"].exists, "no Voice & reply language row")
            XCTAssertFalse(app.staticTexts["Voice & reply language"].exists)
            app.buttons["info-tab-links"].tap()
            XCTAssertTrue(app.buttons["info-tab-links"].isSelected, "Links filter selectable (\(size))")
            shot(app, size.isEmpty ? "info-tabs-default" : "info-tabs-xxl")
            app.terminate()
        }
    }
}
