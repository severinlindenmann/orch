import XCTest

/// The v3 conversation screen against MockRelay: text with receipts, a question with undo, hold-to-record, voice bubble.
final class ConversationUITests: XCTestCase {
    override func setUp() { continueAfterFailure = false }

    private func launch(_ extra: [String]) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES", "-fakeVoice", "YES"] + extra
        app.launch()
        return app
    }
    private func el(_ app: XCUIApplication, _ id: String) -> XCUIElement { app.descendants(matching: .any)[id].firstMatch }

    func testTextSendShowsReceiptAndBubble() {
        let app = launch(["-openChat", "ws_pilatus001"])
        let field = el(app, "composer-field")
        XCTAssertTrue(field.waitForExistence(timeout: 20))
        field.tap(); field.typeText("Please check the totals")
        el(app, "composer-send").tap()
        XCTAssertTrue(app.staticTexts["Please check the totals"].waitForExistence(timeout: 10), "my bubble")
        let any = ["receipt-queued", "receipt-sent", "receipt-delivered", "receipt-started"].contains { el(app, $0).waitForExistence(timeout: 5) }
        XCTAssertTrue(any, "a receipt under my bubble")
        XCTAssertEqual(field.value as? String ?? "", "Message…", "the field is empty again (placeholder)")
    }

    func testQuestionUndoThenAnswered() {
        let app = launch(["-openChat", "ws_pilatus001", "-openTicket", "t_7k3f9q", "-undoSeconds", "3"])
        let timestamp = el(app, "option-TIMESTAMP")
        XCTAssertTrue(timestamp.waitForExistence(timeout: 20))
        timestamp.tap()
        let undo = el(app, "question-undo")
        XCTAssertTrue(undo.waitForExistence(timeout: 5), "the undo window shows")
        undo.tap()
        XCTAssertTrue(el(app, "option-DATE").waitForExistence(timeout: 5), "back to the open question")
        el(app, "option-DATE").tap()
        XCTAssertTrue(el(app, "question-show-other").waitForExistence(timeout: 20), "answered card with Show other options")
        XCTAssertTrue(app.staticTexts["Answered"].exists)
    }

    func testHoldToRecordSendsVoiceNote() {
        let app = launch(["-openChat", "ws_pilatus001"])
        let mic = el(app, "composer-mic")
        XCTAssertTrue(mic.waitForExistence(timeout: 20))
        mic.press(forDuration: 1.6)
        XCTAssertTrue(el(app, "voice-play").waitForExistence(timeout: 20), "the voice note bubble appears")
    }

    func testAttachSheetOffersEveryKind() {
        let app = launch(["-openChat", "ws_pilatus001"])
        let plus = el(app, "composer-attach")
        XCTAssertTrue(plus.waitForExistence(timeout: 20))
        plus.tap()
        for kind in ["camera", "scan", "photos", "files", "location"] {
            XCTAssertTrue(el(app, "attach-\(kind)").waitForExistence(timeout: 5), kind)
        }
    }
}
