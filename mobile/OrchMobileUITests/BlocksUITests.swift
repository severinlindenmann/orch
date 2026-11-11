import XCTest

@MainActor
final class BlocksUITests: XCTestCase {
    func testAllTenPreview() {
        let app = XCUIApplication()
        app.launchArguments = ["-blocksPreview", "valid-all-ten"]
        app.launch()
        XCTAssertTrue(app.otherElements["blocks-view"].waitForExistence(timeout: 10))
        for text in ["Invoice export", "Upload", "No network"] {
            XCTAssertTrue(app.staticTexts[text].exists, text)
        }
    }

    func testInvalidPreview() {
        let app = XCUIApplication()
        app.launchArguments = ["-blocksPreview", "invalid-link-javascript"]
        app.launch()
        // SwiftUI folds the inner "blocks-invalid" container into the outer "blocks-view" element.
        XCTAssertTrue(app.descendants(matching: .any)["blocks-view"].firstMatch.waitForExistence(timeout: 10), app.debugDescription)
        XCTAssertTrue(app.buttons["Details"].exists, app.debugDescription)
        let notice = app.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS %@", "can't be shown")).firstMatch
        XCTAssertTrue(notice.exists, app.debugDescription)
    }
}
