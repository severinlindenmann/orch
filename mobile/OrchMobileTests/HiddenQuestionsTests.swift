import XCTest
@testable import OrchMobile

final class HiddenQuestionsTests: XCTestCase {
    private func suite() -> UserDefaults {
        let name = "hq-\(UUID().uuidString)"
        let d = UserDefaults(suiteName: name)!
        addTeardownBlock { UserDefaults(suiteName: name)?.removePersistentDomain(forName: name) }
        return d
    }
    private let t0 = ISO8601DateFormatter().date(from: "2026-11-14T10:00:00Z")!

    func testHideAndUndo() {
        let store = HiddenQuestions(defaults: suite())
        XCTAssertFalse(store.isHidden("q1", newestActivity: t0))
        store.hide("q1", at: t0.addingTimeInterval(60))
        XCTAssertTrue(store.isHidden("q1", newestActivity: t0))
        store.show("q1")
        XCTAssertFalse(store.isHidden("q1", newestActivity: t0))
        XCTAssertTrue(store.entries.isEmpty)
    }

    func testComesBackWhenTheHelperWritesAgain() {
        let store = HiddenQuestions(defaults: suite())
        store.hide("q1", at: t0)
        XCTAssertTrue(store.isHidden("q1", newestActivity: t0), "same moment stays hidden")
        XCTAssertFalse(store.isHidden("q1", newestActivity: t0.addingTimeInterval(1)), "newer message brings it back")
    }

    func testPersistsAcrossStoreInstances() {
        let d = suite()
        HiddenQuestions(defaults: d).hide("q1", at: t0)
        let again = HiddenQuestions(defaults: d)
        XCTAssertEqual(again.hiddenAt("q1"), t0)
        XCTAssertTrue(again.isHidden("q1", newestActivity: t0))
    }

    func testSwipeOutcomes() {
        XCTAssertEqual(SwipeToHideRules.outcome(offset: -10, width: 360), .springBack)
        XCTAssertEqual(SwipeToHideRules.outcome(offset: -60, width: 360), .reveal)
        XCTAssertEqual(SwipeToHideRules.outcome(offset: -250, width: 360), .hide)
        XCTAssertTrue(SwipeToHideRules.isHorizontal(CGSize(width: -40, height: 5)))
        XCTAssertFalse(SwipeToHideRules.isHorizontal(CGSize(width: 10, height: 40)))
    }
}
