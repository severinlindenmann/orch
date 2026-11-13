import XCTest

/// e2e P4.3: the group approval card is one container element and its answer buttons are found inside it.
final class GroupApprovalUITests: XCTestCase {
    override func setUp() { continueAfterFailure = false }

    @MainActor func testApprovalCardButtonsAreInsideTheCard() {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES", "-mockGroups", "YES"]
        app.launch()
        let any = { (id: String) in app.descendants(matching: .any)[id].firstMatch }
        XCTAssertTrue(any("chat-search").waitForExistence(timeout: 15))
        let row = any("group-13-ws_finance001-grp_t_cartax2027")
        for _ in 0..<6 where !(row.exists && row.isHittable) { app.swipeUp() }
        XCTAssertTrue(row.waitForExistence(timeout: 10)); row.tap()
        let card = any("group-approval")
        // Let the push and the open-at-newest jumps (now and +300 ms) settle: during them the button has no valid frame and
        // isHittable throws instead of returning false.
        XCTAssertTrue(any("group-members").waitForExistence(timeout: 10))
        _ = XCTWaiter.wait(for: [XCTestExpectation(description: "settle")], timeout: 1.0)
        // The room opens at the newest message (e2e P4.8 fix); the approval card is earlier: scroll back up to it.
        let allow = card.buttons["Allow once"]
        let screen = app.windows.firstMatch.frame
        for _ in 0..<8 {
            if allow.exists, !allow.frame.isEmpty, screen.contains(CGPoint(x: allow.frame.midX, y: allow.frame.midY)), allow.isHittable { break }
            any("group-messages").swipeDown()
        }
        XCTAssertEqual(app.descendants(matching: .any).matching(identifier: "group-approval").count, 1, "the card is one element")
        for label in ["Allow once", "Always", "No"] {
            XCTAssertTrue(card.buttons[label].exists, "\(label) inside the card")
        }
        XCTAssertTrue(card.buttons["Allow once"].isHittable)
    }

    /// P54: a group approval waits out the same undo window as a topic answer before it is sent.
    @MainActor func testApprovalCanBeUndoneBeforeItIsSent() {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES", "-mockGroups", "YES", "-undoSeconds", "60"]
        app.launch()
        let any = { (id: String) in app.descendants(matching: .any)[id].firstMatch }
        XCTAssertTrue(any("chat-search").waitForExistence(timeout: 15))
        let row = any("group-13-ws_finance001-grp_t_cartax2027")
        for _ in 0..<6 where !(row.exists && row.isHittable) { app.swipeUp() }
        XCTAssertTrue(row.waitForExistence(timeout: 10)); row.tap()
        let card = any("group-approval")
        XCTAssertTrue(card.buttons["Always"].waitForExistence(timeout: 10))
        _ = XCTWaiter.wait(for: [XCTestExpectation(description: "settle")], timeout: 1.0)
        card.buttons["Always"].tap()
        XCTAssertTrue(any("group-approval-pending").waitForExistence(timeout: 5))
        XCTAssertEqual(any("group-approval-pending").label, "Always · sent in a moment")
        any("group-undo").tap()
        XCTAssertTrue(card.buttons["Always"].waitForExistence(timeout: 5), "undo brings the buttons back")
        XCTAssertFalse(any("group-approval-pending").exists)
    }
}
