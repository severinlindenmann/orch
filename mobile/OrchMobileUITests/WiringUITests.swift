import XCTest

/// W3-A: the M2 conversation wired to the M3 viewer, picker and info screens, against the MockRelay.
final class WiringUITests: XCTestCase {
    override func setUp() { continueAfterFailure = false }

    private func launch(_ extra: [String]) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES", "-fakePhoto", "YES"] + extra
        app.launch()
        return app
    }
    private func el(_ app: XCUIApplication, _ id: String) -> XCUIElement { app.descendants(matching: .any)[id].firstMatch }
    private func must(_ app: XCUIApplication, _ e: XCUIElement, _ what: String, timeout: TimeInterval = 20) {
        if !e.waitForExistence(timeout: timeout) { XCTFail("\(what) missing. Screen: " + String(app.debugDescription.prefix(3500))) }
    }

    /// A result bubble carries the picture; tap -> viewer -> Looks good -> my feedback message with its receipt.
    func testBubbleArtifactOpensViewerAndLooksGoodLandsInTheConversation() {
        let app = launch(["-openChat", "ws_pilatus001", "-openTicket", "t_q3sum1"])
        let card = el(app, "artifact-a_bbbbbbbbbbbb")
        must(app, card, "artifact card in the result bubble")
        card.tap()
        let good = app.buttons["artifact-looks-good"]
        must(app, good, "Looks good in the viewer")
        wait(for: [XCTNSPredicateExpectation(predicate: NSPredicate(format: "isEnabled == true"), object: good)], timeout: 10)
        good.tap()
        XCTAssertFalse(app.buttons["artifact-close"].waitForExistence(timeout: 3), "the viewer closes after sending")
        must(app, app.staticTexts["Looks good"], "my feedback bubble")
        let receipt = ["receipt-queued", "receipt-sent", "receipt-delivered", "receipt-started"].contains { el(app, $0).waitForExistence(timeout: 5) }
        XCTAssertTrue(receipt, "a receipt under the feedback message")
    }

    /// + -> picker -> (test) photo -> Send photo: the photo bubble is in the conversation with a receipt.
    func testPlusPhotoIsSentAsAMessage() {
        let app = launch(["-openChat", "ws_pilatus001"])
        let general = app.buttons["general-ws_pilatus001"]
        must(app, general, "General row"); general.tap()
        let plus = el(app, "composer-attach")
        must(app, plus, "composer +"); plus.tap()
        must(app, app.buttons["media-fake-photo"], "test photo tile"); app.buttons["media-fake-photo"].tap()
        must(app, app.buttons["media-send"], "Send photo"); app.buttons["media-send"].tap()
        XCTAssertFalse(app.buttons["media-send"].waitForExistence(timeout: 3), "the picker closes")
        let image = app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH 'image-'")).firstMatch
        let queued = el(app, "receipt-queued")
        XCTAssertTrue(image.waitForExistence(timeout: 15) || queued.exists || el(app, "receipt-sent").waitForExistence(timeout: 10), "the photo message shows up")
    }

    /// Header info button -> conversation info -> back to the conversation.
    func testHeaderInfoOpensAndGoesBack() {
        let app = launch(["-openChat", "ws_pilatus001", "-openTicket", "t_q3sum1"])
        let info = el(app, "chat-info")
        must(app, info, "info button"); info.tap()
        must(app, app.buttons["info-tab-photos"], "conversation info tabs")
        app.navigationBars.buttons.firstMatch.tap()
        must(app, el(app, "composer"), "back in the conversation")
    }

    /// The agent's spoken answer shows a memo bubble (mock `speak` message).
    func testAgentMemoBubbleIsShown() {
        let app = launch(["-openChat", "ws_pilatus001"])
        let general = app.buttons["general-ws_pilatus001"]
        must(app, general, "General row"); general.tap()
        must(app, el(app, "voice-play"), "memo play button")
    }

    /// Screenshots for the PR when the shots folder exists.
    func testShots() throws {
        let home = ProcessInfo.processInfo.environment["SIMULATOR_HOST_HOME"] ?? NSHomeDirectory()
        let out = URL(fileURLWithPath: home).appendingPathComponent("orch-dev/state/mobile-v3-messenger/build/shots/w3a")
        try XCTSkipUnless(FileManager.default.fileExists(atPath: out.path), "no shots folder")
        func snap(_ app: XCUIApplication, _ name: String) throws { sleep(2); try app.screenshot().pngRepresentation.write(to: out.appendingPathComponent("app-\(name).png")) }
        var app = launch(["-openChat", "ws_pilatus001", "-openTicket", "t_q3sum1"])
        must(app, el(app, "artifact-a_bbbbbbbbbbbb"), "card"); try snap(app, "1-topic-result-card")
        el(app, "chat-info").tap(); must(app, app.buttons["info-tab-photos"], "info"); try snap(app, "2-info")
        app.terminate()
        app = launch(["-openChat", "ws_pilatus001"])
        must(app, app.buttons["general-ws_pilatus001"], "general"); app.buttons["general-ws_pilatus001"].tap()
        must(app, el(app, "voice-play"), "memo"); try snap(app, "3-general-memo")
        el(app, "composer-attach").tap(); must(app, app.buttons["media-fake-photo"], "picker"); try snap(app, "4-picker")
        app.buttons["media-fake-photo"].tap(); must(app, app.buttons["media-send"], "preview"); try snap(app, "5-photo-preview")
        app.buttons["media-send"].tap(); sleep(3); try snap(app, "6-photo-sent")
    }
}
