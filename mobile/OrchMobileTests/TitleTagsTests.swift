import XCTest
@testable import OrchMobile

final class TitleTagsTests: XCTestCase {
    func testHidesTestRunTagsAndStamps() {
        XCTAssertEqual(TitleTags.clean("[R] Fix the invoice export"), "Fix the invoice export")
        XCTAssertEqual(TitleTags.clean("[E2E][R] Fix it [0722]"), "Fix it")
        XCTAssertEqual(TitleTags.clean("Plan trip [2026-11-12T10:00Z]"), "Plan trip")
        XCTAssertEqual(TitleTags.clean("Plan [Q3] budget"), "Plan [Q3] budget")
    }
    func testTitleThatIsOnlyTagsStaysAsItIs() { XCTAssertEqual(TitleTags.clean("[R]"), "[R]") }
}
