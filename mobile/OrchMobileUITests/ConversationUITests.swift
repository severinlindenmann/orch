import XCTest

/// The v3 conversation screen against MockRelay: text with receipts, a question with undo, hold-to-record, voice bubble.
final class ConversationUITests: XCTestCase {
    override func setUp() { continueAfterFailure = false }

    private func launch(_ extra: [String]) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES", "-fakeVoice", "YES"] + extra
        app.launch()
        // -openChat lands on the workspace page (General row + topics): open General when that is what we asked for.
        if !extra.contains("-openTicket"), let g = Optional(app.buttons["general-ws_pilatus001"]), g.waitForExistence(timeout: 15) { g.tap() }
        return app
    }
    /// Waits for an element; on failure the message carries the screen's accessibility tree (CI logs are quiet).
    private func must(_ app: XCUIApplication, _ e: XCUIElement, _ what: String, timeout: TimeInterval = 20) {
        if !e.waitForExistence(timeout: timeout) { XCTFail("\(what) missing. Screen: " + String(app.debugDescription.prefix(3500))) }
    }
    private func el(_ app: XCUIApplication, _ id: String) -> XCUIElement { app.descendants(matching: .any)[id].firstMatch }

    func testTextSendShowsReceiptAndBubble() {
        let app = launch(["-openChat", "ws_pilatus001"])
        let field = el(app, "composer-field")
        must(app, field, "composer-field")
        field.tap(); field.typeText("Please check the totals")
        el(app, "composer-send").tap()
        XCTAssertTrue(app.staticTexts["Please check the totals"].waitForExistence(timeout: 10), "my bubble")
        let any = ["receipt-queued", "receipt-sent", "receipt-delivered", "receipt-started"].contains { el(app, $0).waitForExistence(timeout: 5) }
        XCTAssertTrue(any, "a receipt under my bubble")
        XCTAssertFalse((field.value as? String ?? "").contains("totals"), "the field is empty again")
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
        must(app, mic, "composer-mic")
        mic.press(forDuration: 1.6)
        XCTAssertTrue(el(app, "voice-play").waitForExistence(timeout: 20), "the voice note bubble appears")
    }

    func testStartedChipOpensTheTopicOncePerAck() {
        let app = launch(["-openChat", "ws_pilatus001"])
        let field = el(app, "composer-field")
        must(app, field, "composer-field")
        field.tap(); field.typeText("Start the board summary")
        el(app, "composer-send").tap()
        let chip = app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH 'started-chip-'")).firstMatch
        XCTAssertTrue(chip.waitForExistence(timeout: 15), "the ack that names a ticket shows a chip")
        XCTAssertTrue(chip.label.contains("started"))
        XCTAssertEqual(app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH 'started-chip-'")).count, 1, "one chip per ack")
        chip.tap()
        must(app, el(app, "composer"), "the topic screen")
        XCTAssertTrue(el(app, "chat-title").waitForExistence(timeout: 5))
    }

    func testAttachSheetOffersEveryKind() {
        let app = launch(["-openChat", "ws_pilatus001"])
        let plus = el(app, "composer-attach")
        must(app, plus, "composer-attach")
        plus.tap()
        for kind in ["camera", "scan", "photos", "files", "location"] {
            XCTAssertTrue(el(app, "attach-\(kind)").waitForExistence(timeout: 5), kind)
        }
    }
}
