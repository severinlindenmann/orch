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

final class NewTopicAfterSendTests: XCTestCase {
    private func topic(_ id: ConversationID, at: String, starting: Bool) -> TopicSummary {
        TopicSummary(id: id, title: "t", key: nil, status: .working, lastLine: "", lastAt: at, unread: 0, isStarting: starting, ticket: nil)
    }
    func testAfterSendOpensTheStartingChatOnTopOfTheWorkspace() {
        let topics = [topic(.topic(workspace: "w", ticket: "t_old"), at: "2026-11-14T10:00:00Z", starting: false),
                      topic(.starting(workspace: "w", id: "c1"), at: "2026-11-14T11:00:00Z", starting: true)]
        XCTAssertEqual(NewTopicRules.pathAfterSend(workspace: "w", topics: topics), [.workspace("w"), .starting(workspace: "w", id: "c1")])
    }
    func testAfterSendOpensTheTicketWhenTheAckAlreadyCame() {
        let topics = [topic(.topic(workspace: "w", ticket: "t_new"), at: "2026-11-14T11:00:00Z", starting: false)]
        XCTAssertEqual(NewTopicRules.pathAfterSend(workspace: "w", topics: topics), [.workspace("w"), .ticket(workspace: "w", ticket: "t_new")])
    }
    func testAfterSendWithNothingFoundStaysOnTheWorkspace() {
        XCTAssertEqual(NewTopicRules.pathAfterSend(workspace: "w", topics: []), [.workspace("w")])
    }
}
