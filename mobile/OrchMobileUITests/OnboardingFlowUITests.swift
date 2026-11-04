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
        XCTAssertTrue(app.staticTexts["Answer sent to workspace"].waitForExistence(timeout: 10))

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
}
