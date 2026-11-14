import XCTest
@testable import OrchMobile

final class NewTopicRulesTests: XCTestCase {
    func testInitialSelectionPrefersLastUsedThenOpenerThenFirst() {
        let ids = ["a", "b", "c"]
        XCTAssertEqual(NewTopicRules.initialSelection(ids: ids, lastUsed: "c", opener: "b"), "c")
        XCTAssertEqual(NewTopicRules.initialSelection(ids: ids, lastUsed: "gone", opener: "b"), "b")
        XCTAssertEqual(NewTopicRules.initialSelection(ids: ids, lastUsed: nil, opener: nil), "a")
        XCTAssertNil(NewTopicRules.initialSelection(ids: [], lastUsed: "a", opener: nil))
    }
    func testTilesPutLastUsedFirstAndCapAtThree() {
        let ids = ["a", "b", "c", "d", "e"]
        XCTAssertEqual(NewTopicRules.tiles(ids: ids, preferred: "d", selected: "d"), ["d", "a", "b"])
        XCTAssertTrue(NewTopicRules.hasMore(count: ids.count))
        XCTAssertFalse(NewTopicRules.hasMore(count: 3))
    }
    func testPickedWorkspaceFromMoreStaysVisible() {
        XCTAssertEqual(NewTopicRules.tiles(ids: ["a", "b", "c", "d", "e"], preferred: "a", selected: "e"), ["a", "b", "e"])
    }
    func testOneWorkspaceHasOneTileAndNoMore() {
        XCTAssertEqual(NewTopicRules.tiles(ids: ["a"], preferred: nil, selected: "a"), ["a"])
        XCTAssertFalse(NewTopicRules.hasMore(count: 1))
    }
    func testAutoMicOpensRecordingOnlyWithAWorkspace() {
        XCTAssertTrue(NewTopicRules.opensRecording(autoMic: true, hasWorkspace: true))
        XCTAssertFalse(NewTopicRules.opensRecording(autoMic: false, hasWorkspace: true))
        XCTAssertFalse(NewTopicRules.opensRecording(autoMic: true, hasWorkspace: false))
    }
    func testOneSecondMinimum() {
        let url = URL(fileURLWithPath: "/tmp/x.m4a")
        XCTAssertFalse(NewTopicRules.longEnough([VoiceSegment(url: url, duration: 0.9)]))
        XCTAssertTrue(NewTopicRules.longEnough([VoiceSegment(url: url, duration: 1.0)]))
        XCTAssertTrue(NewTopicRules.longEnough([VoiceSegment(url: url, duration: 0.6), VoiceSegment(url: url, duration: 0.6)]))
        XCTAssertFalse(NewTopicRules.longEnough([]))
    }
    func testClock() {
        XCTAssertEqual(NewTopicRules.clock(0), "00:00")
        XCTAssertEqual(NewTopicRules.clock(75.9), "01:15")
    }
}
