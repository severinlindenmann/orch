import XCTest

/// Click-through against the in-process MockRelay: onboarding, home, questions, answer, typed send.
final class OnboardingFlowUITests: XCTestCase {
    override func setUp() { continueAfterFailure = false }

    func testOnboardingToAnswerToTypedSend() {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock"]
        app.launch()

        // Onboarding: sample invitation, connect, skip notifications
        XCTAssertTrue(app.staticTexts["Let's get connected"].waitForExistence(timeout: 10))
        app.buttons["sample-invite"].tap()
        let connect = app.buttons["Connect this phone"]
        XCTAssertTrue(connect.waitForExistence(timeout: 5))
        connect.tap()
        let notNow = app.buttons["Not now"]
        XCTAssertTrue(notNow.waitForExistence(timeout: 10))
        notNow.tap()

        // Home: both mock workspaces, open questions banner
        XCTAssertTrue(app.staticTexts["Your workspaces"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.staticTexts["Data pipelines for the Pilatus client"].waitForExistence(timeout: 10))

        // Questions: answer with one tap
        app.buttons["Questions"].tap()
        let answer = app.buttons["answer-TIMESTAMP"]
        XCTAssertTrue(answer.waitForExistence(timeout: 10))
        answer.tap()
        XCTAssertTrue(app.staticTexts["Answer sent: TIMESTAMP"].waitForExistence(timeout: 10))

        // Send: typed text to a workspace inbox
        app.buttons["Send"].tap()
        let field = app.textViews["transcript"]
        XCTAssertTrue(field.waitForExistence(timeout: 5))
        field.tap()
        field.typeText("Hello from the UI test")
        let send = app.buttons["send-button"]
        if !send.isHittable { app.swipeUp() }
        send.tap()
        XCTAssertTrue(app.staticTexts["It's in the inbox."].waitForExistence(timeout: 10))
    }

    /// Mic path against the mock: scripted recorder, tap to record, tap to stop, transcript appears, edit, send.
    func testVoiceSendFlow() {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES", "-startTab", "send"]
        app.launch()
        let mic = app.buttons["mic"]
        XCTAssertTrue(mic.waitForExistence(timeout: 15))
        mic.tap()
        XCTAssertTrue(app.staticTexts["Recording your voice… tap to stop"].waitForExistence(timeout: 5))
        sleep(1)
        mic.tap()
        let field = app.textViews["transcript"]
        let predicate = NSPredicate(format: "value CONTAINS 'weekly report'")
        let e = XCTNSPredicateExpectation(predicate: predicate, object: field)
        XCTAssertEqual(XCTWaiter().wait(for: [e], timeout: 10), .completed)
        let send = app.buttons["send-button"]
        if !send.isHittable { app.swipeUp() }
        send.tap()
        XCTAssertTrue(app.staticTexts["It's in the inbox."].waitForExistence(timeout: 10))
    }

    /// Answer has a 3 s undo window; undo returns the options and nothing is sent.
    func testAnswerCanBeUndone() {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES", "-startTab", "questions", "-undoSeconds", "30"]
        app.launch()
        let answer = app.buttons["answer-TIMESTAMP"]
        XCTAssertTrue(answer.waitForExistence(timeout: 15))
        answer.tap()
        let undo = app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH 'undo-'")).firstMatch
        XCTAssertTrue(undo.waitForExistence(timeout: 10))
        undo.tap()
        XCTAssertTrue(app.buttons["answer-TIMESTAMP"].waitForExistence(timeout: 3))
        XCTAssertFalse(app.staticTexts["Answer sent: TIMESTAMP"].exists)
    }

    /// VoiceOver label audit: every button on the main screens has a spoken label (no empty or raw-symbol names).
    func testEveryButtonHasALabel() {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES"]
        app.launch()
        XCTAssertTrue(app.staticTexts["Your workspaces"].waitForExistence(timeout: 15))
        for tab in ["Home", "Questions", "Send", "Settings"] {
            app.buttons[tab].tap()
            sleep(1)
            for b in app.buttons.allElementsBoundByIndex where b.exists && b.isHittable {
                XCTAssertFalse(b.label.trimmingCharacters(in: .whitespaces).isEmpty, "unlabelled button on \(tab): \(b.identifier)")
            }
        }
    }

    /// Send is never silently disabled: tapping it empty explains what is missing.
    func testSendExplainsWhyNothingHappens() {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES", "-startTab", "send"]
        app.launch()
        let send = app.buttons["send-button"]
        XCTAssertTrue(send.waitForExistence(timeout: 15))
        if !send.isHittable { app.swipeUp() }
        send.tap()
        XCTAssertTrue(app.staticTexts["send-hint"].waitForExistence(timeout: 3))
    }

    /// A bad invitation link keeps the sheet open and the typed text, and says what to do next.
    func testBadInviteLinkKeepsInputAndExplains() {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock"]
        app.launch()
        app.buttons["Paste invitation link"].tap()
        let field = app.textFields["invite-field"]
        XCTAssertTrue(field.waitForExistence(timeout: 10))
        field.tap()
        field.typeText("https://example.com/nope")
        app.buttons["invite-continue"].tap()
        XCTAssertTrue(app.staticTexts["invite-error"].waitForExistence(timeout: 3))
        XCTAssertTrue((app.staticTexts["invite-error"].label).contains("ask the person who invited you"))
        XCTAssertEqual(app.textFields["invite-field"].value as? String, "https://example.com/nope")
    }

    /// Return submits the invitation sheet; an expired code gets the friendly text and keeps the input.
    func testExpiredInviteViaReturnKeepsInput() {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock"]
        app.launch()
        app.buttons["Paste invitation link"].tap()
        let field = app.textFields["invite-field"]
        XCTAssertTrue(field.waitForExistence(timeout: 10))
        field.tap()
        field.typeText("orch://pair?relay=https%3A%2F%2Frelay.severin.io&code=pc_expired0000000000000000\n")
        let connect = app.buttons["Connect this phone"]
        XCTAssertTrue(connect.waitForExistence(timeout: 5))
        connect.tap()
        XCTAssertTrue(app.staticTexts.containing(NSPredicate(format: "label CONTAINS 'expired or was already used'")).firstMatch.waitForExistence(timeout: 10))
        XCTAssertTrue(app.buttons["Connect this phone"].exists)
    }

    /// Offline before any load: Send says the connection is the problem, not "Pick a workspace".
    func testOfflineSendTabExplainsConnection() {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES", "-mockFail", "YES", "-startTab", "send"]
        app.launch()
        XCTAssertTrue(app.staticTexts["Can't load your workspaces"].waitForExistence(timeout: 15))
        XCTAssertTrue(app.buttons["send-retry"].exists)
        XCTAssertFalse(app.staticTexts["Pick a workspace first."].exists)
    }

    /// The sent screen's "Back to home" is a full-size target.
    func testBackToHomeTargetIsLargeEnough() {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES", "-startTab", "send"]
        app.launch()
        let field = app.textViews["transcript"]
        XCTAssertTrue(field.waitForExistence(timeout: 15))
        field.tap(); field.typeText("Hello")
        app.buttons["keyboard-done"].tap()
        let send = app.buttons["send-button"]
        if !send.isHittable { app.swipeUp() }
        send.tap()
        let back = app.buttons["Back to home →"]
        XCTAssertTrue(back.waitForExistence(timeout: 10))
        XCTAssertGreaterThanOrEqual(back.frame.height, 44)
    }

    /// Server unreachable: no "All clear", no "Connected", a plain way to retry.
    func testUnreachableServerIsHonest() {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES", "-mockFail", "YES"]
        app.launch()
        XCTAssertTrue(app.staticTexts["Can't reach your workspaces."].waitForExistence(timeout: 15))
        XCTAssertFalse(app.staticTexts["All clear. Nothing needs you right now."].exists)
        XCTAssertTrue(app.buttons["Try again"].exists || app.buttons["Trying again…"].exists)
        app.buttons["Settings"].tap()
        XCTAssertTrue(app.staticTexts["●  Can't reach the server"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.staticTexts["●  Connected"].exists)
    }

    /// The whole Sign out box is a tap target (left edge, not only the label).
    func testSignOutBoxIsFullyTappable() {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES", "-startTab", "settings"]
        app.launch()
        let box = app.buttons["Sign out"]
        XCTAssertTrue(box.waitForExistence(timeout: 15))
        XCTAssertGreaterThanOrEqual(box.frame.height, 44)
        box.coordinate(withNormalizedOffset: CGVector(dx: 0.03, dy: 0.5)).tap()
        XCTAssertTrue(app.buttons["signout-confirm"].waitForExistence(timeout: 3))
    }

    /// The tab bar column is tappable outside the icon and label.
    func testTabsAreFullHeightTargets() {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES"]
        app.launch()
        let tab = app.buttons["Send"]
        XCTAssertTrue(tab.waitForExistence(timeout: 15))
        XCTAssertGreaterThanOrEqual(tab.frame.height, 44)
        tab.coordinate(withNormalizedOffset: CGVector(dx: 0.2, dy: 0.2)).tap()
        XCTAssertTrue(app.staticTexts["Say it. Send it"].waitForExistence(timeout: 3))
    }
}
