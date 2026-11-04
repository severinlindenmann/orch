import XCTest

/// Click-through against the in-process MockRelay: onboarding, home, questions, answer, typed send.
final class OnboardingFlowUITests: XCTestCase {
    override func setUp() { continueAfterFailure = false }

    func testOnboardingToAnswerToTypedSend() {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock"]
        app.launch()

        // Onboarding: sample invitation, connect, skip notifications
        XCTAssertTrue(app.staticTexts["Let's get connected."].waitForExistence(timeout: 10))
        app.buttons["sample-invite"].tap()
        let connect = app.buttons["Connect this phone"]
        XCTAssertTrue(connect.waitForExistence(timeout: 5))
        connect.tap()
        let notNow = app.buttons["Not now"]
        XCTAssertTrue(notNow.waitForExistence(timeout: 10))
        notNow.tap()

        // Home: both mock workspaces, open questions banner
        XCTAssertTrue(app.staticTexts["Your workspaces."].waitForExistence(timeout: 10))
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
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES", "-startTab", "questions"]
        app.launch()
        let answer = app.buttons["answer-TIMESTAMP"]
        XCTAssertTrue(answer.waitForExistence(timeout: 15))
        answer.tap()
        let undo = app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH 'undo-'")).firstMatch
        XCTAssertTrue(undo.waitForExistence(timeout: 3))
        undo.tap()
        XCTAssertTrue(app.buttons["answer-TIMESTAMP"].waitForExistence(timeout: 3))
        XCTAssertFalse(app.staticTexts["Answer sent: TIMESTAMP"].exists)
    }

    /// VoiceOver label audit: every button on the main screens has a spoken label (no empty or raw-symbol names).
    func testEveryButtonHasALabel() {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES"]
        app.launch()
        XCTAssertTrue(app.staticTexts["Your workspaces."].waitForExistence(timeout: 15))
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
}
