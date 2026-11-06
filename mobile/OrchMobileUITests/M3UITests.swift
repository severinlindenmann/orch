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

    func testLooksGoodOnAPageSendsApproveFeedback() throws {
        let app = launch("viewer-html")
        XCTAssertTrue(app.buttons["artifact-looks-good"].waitForExistence(timeout: 20))
        XCTAssertTrue(app.webViews.firstMatch.waitForExistence(timeout: 10))
        app.buttons["artifact-looks-good"].tap()
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
        app.windows.firstMatch.coordinate(withNormalizedOffset: CGVector(dx: 0.3, dy: 0.35)).tap()
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
        app.buttons["artifact-looks-good"].tap()
        XCTAssertTrue(app.staticTexts["feedback sent: 1"].waitForExistence(timeout: 10))
    }

    func testMediaPickerOffersTheFourSources() throws {
        let app = launch("picker")
        for id in ["media-camera", "media-photos", "media-files", "media-location"] {
            XCTAssertTrue(app.buttons[id].waitForExistence(timeout: 20), id)
        }
        app.buttons["media-close"].tap()
        XCTAssertTrue(app.buttons["demo-open-picker"].waitForExistence(timeout: 5))
    }

    func testConversationInfoGroupsAndLanguage() throws {
        let app = launch("info")
        XCTAssertTrue(app.buttons["demo-open-info"].waitForExistence(timeout: 20))
        app.buttons["demo-open-info"].tap()
        XCTAssertTrue(app.buttons["info-tab-photos"].waitForExistence(timeout: 10))
        for t in ["photos", "files", "links", "artifacts"] { XCTAssertTrue(app.buttons["info-tab-\(t)"].exists, t) }
        app.buttons["info-tab-photos"].tap()
        app.buttons["info-language-row"].tap()
        XCTAssertTrue(app.switches.firstMatch.waitForExistence(timeout: 5), "Swiss German toggle")
    }
}
