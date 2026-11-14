import XCTest

final class MuteUITests: XCTestCase {
    override func setUp() { continueAfterFailure = false }

    func testMuteAllAndTurnOn() {
        let app = XCUIApplication()
        app.launchArguments = ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES"]
        app.launch()
        XCTAssertTrue(app.buttons["settings-button"].waitForExistence(timeout: 15))
        app.buttons["settings-button"].tap()
        let toggle = app.switches["mute-all"]
        XCTAssertTrue(toggle.waitForExistence(timeout: 5))
        toggle.tap()
        XCTAssertTrue(app.buttons["1 hour"].waitForExistence(timeout: 5))
        app.buttons["1 hour"].tap()
        let enabled = XCTNSPredicateExpectation(predicate: NSPredicate(format: "value == '1'"), object: toggle)
        XCTAssertEqual(XCTWaiter.wait(for: [enabled], timeout: 5), .completed)
        app.navigationBars.buttons.firstMatch.tap()
        let banner = app.descendants(matching: .any)["mute-all-banner"].firstMatch
        XCTAssertTrue(banner.waitForExistence(timeout: 5))
        app.buttons["mute-all-off"].tap()
        let gone = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: banner)
        XCTAssertEqual(XCTWaiter.wait(for: [gone], timeout: 5), .completed)
    }

    func testWorkspaceMuteShowsOnRow() {
        let app = XCUIApplication()
        app.launchArguments = ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES", "-openChat", "ws_pilatus001"]
        app.launch()
        let mute = app.buttons["chat-mute"]
        XCTAssertTrue(mute.waitForExistence(timeout: 15))
        mute.tap()
        let forever = app.buttons["Until I unmute"]
        XCTAssertTrue(forever.waitForExistence(timeout: 5))
        forever.tap()
        let unmuting = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label == 'Unmute'"), object: mute)
        XCTAssertEqual(XCTWaiter.wait(for: [unmuting], timeout: 5), .completed)
        // -openChat may sit below the workspace screen: go back until the Chats list shows.
        let row = app.buttons["room-ws_pilatus001"]
        for _ in 0..<3 where !row.exists {
            let back = app.buttons["BackButton"].firstMatch
            guard back.waitForExistence(timeout: 3) else { break }
            back.tap()
            _ = row.waitForExistence(timeout: 3)
        }
        XCTAssertTrue(row.waitForExistence(timeout: 5))
        // The row is one button: its children (the bell-slash) are merged into its label.
        XCTAssertTrue(row.images["Muted"].exists || row.label.contains("Muted"), "row label: \(row.label)")
    }

    func testX8MuteOneWorkspaceOthersStillOn() {
        let app = XCUIApplication()
        app.launchArguments = ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES", "-openChat", "ws_reports001"]
        app.launch()
        let mute = app.buttons["chat-mute"]
        XCTAssertTrue(mute.waitForExistence(timeout: 15))
        waitForLabel("Mute", on: mute)
        mute.tap()
        let forever = app.buttons["Until I unmute"]
        XCTAssertTrue(forever.waitForExistence(timeout: 5))
        forever.tap()
        waitForLabel("Unmute", on: mute)

        returnToChats(app, workspace: "ws_reports001")
        let reports = app.buttons["room-ws_reports001"]
        let pilatus = app.buttons["room-ws_pilatus001"]
        waitForMutedRow(reports, muted: true)
        XCTAssertTrue(pilatus.waitForExistence(timeout: 5))
        waitForMutedRow(pilatus, muted: false)

        reports.tap()
        XCTAssertTrue(mute.waitForExistence(timeout: 5))
        waitForLabel("Unmute", on: mute)
        mute.tap()
        waitForLabel("Mute", on: mute)
        returnToChats(app, workspace: "ws_reports001")
        waitForMutedRow(reports, muted: false)
    }

    func testMuteOneGroup() {
        let app = XCUIApplication()
        app.launchArguments = ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES", "-mockMuteGroupPair", "YES"]
        app.launch()
        XCTAssertTrue(app.descendants(matching: .any)["chat-search"].firstMatch.waitForExistence(timeout: 15))
        // Existing group UI tests navigate via the list; there is no group launch route.
        openGroup(app, host: "ws_finance001")
        let mute = app.buttons["chat-mute"]
        waitForLabel("Mute", on: mute)
        mute.tap()
        XCTAssertTrue(app.buttons["1 hour"].waitForExistence(timeout: 5))
        app.buttons["1 hour"].tap()
        waitForLabel("Unmute", on: mute)
        XCTAssertTrue(app.buttons["group-back"].waitForExistence(timeout: 5))
        app.buttons["group-back"].tap()

        openGroup(app, host: "ws_home000001")
        waitForLabel("Mute", on: mute)
        app.buttons["group-back"].tap()
        openGroup(app, host: "ws_finance001")
        waitForLabel("Unmute", on: mute)
    }

    func testMuteAllShowsBannerAcrossScreens() {
        let app = XCUIApplication()
        let arguments = ["-relayMode", "mock", "-seedPaired", "YES", "-mockPersistMuteAll", "YES"]
        app.launchArguments = ["-resetState", "YES"] + arguments
        app.launch()
        XCTAssertTrue(app.buttons["settings-button"].waitForExistence(timeout: 15))
        app.buttons["settings-button"].tap()
        let toggle = app.switches["mute-all"]
        XCTAssertTrue(toggle.waitForExistence(timeout: 5))
        toggle.tap()
        XCTAssertTrue(app.buttons["1 hour"].waitForExistence(timeout: 5))
        app.buttons["1 hour"].tap()
        let enabled = XCTNSPredicateExpectation(predicate: NSPredicate(format: "value == '1'"), object: toggle)
        XCTAssertEqual(XCTWaiter.wait(for: [enabled], timeout: 5), .completed)
        app.navigationBars.buttons.firstMatch.tap()
        let banner = app.descendants(matching: .any)["mute-all-banner"].firstMatch
        XCTAssertTrue(banner.waitForExistence(timeout: 5))
        let room = app.buttons["room-ws_pilatus001"]
        XCTAssertTrue(room.waitForExistence(timeout: 5))
        room.tap()
        XCTAssertTrue(app.buttons["chat-mute"].waitForExistence(timeout: 5))
        returnToChats(app, workspace: "ws_pilatus001")
        XCTAssertTrue(banner.waitForExistence(timeout: 5))

        app.terminate()
        app.launchArguments = arguments // Preserve the fake relay's state across the process restart.
        app.launch()
        XCTAssertTrue(room.waitForExistence(timeout: 15))
        XCTAssertTrue(banner.waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["mute-all-off"].waitForExistence(timeout: 5))
        app.buttons["mute-all-off"].tap()
        let gone = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: banner)
        XCTAssertEqual(XCTWaiter.wait(for: [gone], timeout: 5), .completed)
    }

    private func waitForLabel(_ label: String, on element: XCUIElement) {
        XCTAssertTrue(element.waitForExistence(timeout: 5))
        let expectation = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label == %@", label), object: element)
        XCTAssertEqual(XCTWaiter.wait(for: [expectation], timeout: 5), .completed)
    }

    private func waitForMutedRow(_ row: XCUIElement, muted: Bool) {
        XCTAssertTrue(row.waitForExistence(timeout: 5))
        let predicate = NSPredicate { object, _ in
            guard let row = object as? XCUIElement, row.exists else { return false }
            return (row.images["Muted"].exists || row.label.contains("Muted")) == muted
        }
        let expectation = XCTNSPredicateExpectation(predicate: predicate, object: row)
        XCTAssertEqual(XCTWaiter.wait(for: [expectation], timeout: 5), .completed, "row label: \(row.label)")
    }

    private func returnToChats(_ app: XCUIApplication, workspace: String) {
        let row = app.buttons["room-" + workspace]
        for _ in 0..<3 where !row.exists {
            let back = app.buttons["BackButton"].firstMatch
            guard back.waitForExistence(timeout: 3) else { break }
            back.tap()
            _ = row.waitForExistence(timeout: 3)
        }
        XCTAssertTrue(row.waitForExistence(timeout: 5))
    }

    private func openGroup(_ app: XCUIApplication, host: String) {
        let row = app.descendants(matching: .any)["group-\(host.utf8.count)-\(host)-grp_t_mutepair"].firstMatch
        XCTAssertTrue(app.descendants(matching: .any)["chat-search"].firstMatch.waitForExistence(timeout: 5))
        for _ in 0..<6 where !(row.exists && row.isHittable) { app.swipeUp() }
        // Returning from a room preserves the list offset; the other host may be above it.
        for _ in 0..<6 where !(row.exists && row.isHittable) { app.swipeDown() }
        XCTAssertTrue(row.waitForExistence(timeout: 5))
        XCTAssertTrue(row.isHittable)
        row.tap()
        XCTAssertTrue(app.buttons["group-members"].waitForExistence(timeout: 5))
        XCTAssertEqual(app.buttons["group-members"].label, "Mute isolation")
    }

}
