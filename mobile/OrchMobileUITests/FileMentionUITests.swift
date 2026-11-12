import XCTest

final class FileMentionUITests: XCTestCase {
    override func setUp() { continueAfterFailure = false }

    func testWorkspaceFileMentionOpensArtifact() {
        let app = XCUIApplication()
        app.launchArguments += ["-resetState", "YES", "-relayMode", "mock", "-seedPaired", "YES",
                                "-open", "topic:ws_pilatus001:t_q3sum1"]
        app.launch()

        let bubble = app.staticTexts.matching(NSPredicate(
            format: "label BEGINSWITH %@ AND label CONTAINS %@", "Q3 summary is ready.", "notes/old-plan.md"
        )).firstMatch
        XCTAssertTrue(bubble.waitForExistence(timeout: 20))
        XCTAssertFalse(app.links.matching(NSPredicate(format: "label CONTAINS %@", "old-plan")).firstMatch.exists)

        let mention = app.links.matching(NSPredicate(format: "label CONTAINS %@", "artifacts/test-report.pdf")).firstMatch
        if mention.exists {
            mention.tap()
        } else {
            // The filename is the first line; tap within it if SwiftUI exposes only the enclosing Text.
            bubble.coordinate(withNormalizedOffset: CGVector(dx: 0, dy: 0))
                .withOffset(CGVector(dx: 35, dy: 10)).tap()
        }
        XCTAssertTrue(app.buttons["artifact-close"].waitForExistence(timeout: 10))
    }
}
