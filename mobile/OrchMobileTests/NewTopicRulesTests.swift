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

final class NewTopicVoiceFlowTests: XCTestCase {
    func testDoneThenTranscriptShowsReview() {
        var f = NewTopicVoiceFlow(); XCTAssertEqual(f.phase, .recording)
        f.done(); XCTAssertEqual(f.phase, .transcribing)
        f.transcribed(["Hello there"]); XCTAssertEqual(f.phase, .review)
        XCTAssertEqual(f.transcript, "Hello there"); XCTAssertTrue(f.canSend)
    }
    func testRecordMoreAppendsTheNextTake() {
        var f = NewTopicVoiceFlow(); f.done(); f.transcribed(["One"])
        f.recordMore(); XCTAssertEqual(f.phase, .recording)
        f.done(); f.transcribed(["Two", "Three"])
        XCTAssertEqual(f.transcript, "One\n\nTwo\n\nThree")
    }
    func testEditReplacesTranscriptAndRecordMoreKeepsIt() {
        var f = NewTopicVoiceFlow(); f.done(); f.transcribed(["Hello"])
        f.edit(); XCTAssertEqual(f.phase, .editing); XCTAssertEqual(f.transcript, "Hello")
        f.setEdited("Hello, fixed"); XCTAssertEqual(f.transcript, "Hello, fixed")
        f.sending(); f.sendFailed(); XCTAssertEqual(f.phase, .editing)
    }
    func testEmptyEditCannotSend() {
        var f = NewTopicVoiceFlow(); f.done(); f.transcribed(["Hello"]); f.edit(); f.setEdited("  ")
        XCTAssertFalse(f.canSend)
    }
    func testFailureOffersVoiceOnlyAndRetry() {
        var f = NewTopicVoiceFlow(); f.done(); f.transcriptionFailed()
        XCTAssertEqual(f.phase, .failed); XCTAssertTrue(f.canSendVoiceOnly); XCTAssertFalse(f.canSend)
        f.retry(); XCTAssertEqual(f.phase, .transcribing)
        f.transcribed(["", " "]); XCTAssertEqual(f.phase, .failed)
        f.sending(); XCTAssertEqual(f.phase, .sending)
        f.sendFailed(); XCTAssertEqual(f.phase, .failed)
    }
    func testTranscriptsGoWithFirstSegmentOnly() {
        XCTAssertEqual(NewTopicVoiceFlow.transcripts(text: "All", segmentCount: 3, voiceOnly: false), ["All", "", ""])
        XCTAssertEqual(NewTopicVoiceFlow.transcripts(text: "All", segmentCount: 2, voiceOnly: true), ["", ""])
        XCTAssertEqual(NewTopicVoiceFlow.transcripts(text: "x", segmentCount: 0, voiceOnly: false), [])
    }
}
