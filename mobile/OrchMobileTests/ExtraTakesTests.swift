import XCTest
@testable import OrchMobile

/// "Record more" on New topic: extra takes must not be lost when the workspace's ack is late (#720).
@MainActor
final class ExtraTakesTests: XCTestCase {
    private var dir: URL!
    override func setUp() { dir = FileManager.default.temporaryDirectory.appendingPathComponent("takes-\(UUID().uuidString)") }
    override func tearDown() { try? FileManager.default.removeItem(at: dir) }

    private func voiceDraft(_ name: String) throws -> MessageDraft {
        let f = dir.appendingPathComponent(name)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        try Data(repeating: 1, count: 64).write(to: f)
        return MessageDraft(voice: DraftVoice(url: f, duration: 3, transcript: "more", lang: "en", langSource: .detected))
    }

    func testWaitingTakeIsKeptAndNeverSentAsANewTopic() throws {
        let box = Outbox(directory: dir.appendingPathComponent("outbox"), phone: "ph_a")
        let take = try box.enqueue(voiceDraft("t.m4a"), to: .newTopic(workspace: "ws_abcdefghij"), joinAfter: "first-client-id")
        XCTAssertFalse(try XCTUnwrap(box.item(clientId: take.clientId)).isNewTopic, "no phantom 'starting' topic row")
        box.flushWrites()
        let again = Outbox(directory: dir.appendingPathComponent("outbox"), phone: "ph_a")
        XCTAssertEqual(again.items.first?.joinAfter, "first-client-id", "survives a restart")
    }

    func testTakeJoinsItsTopicOnceTheAckIsKnown() throws {
        let box = Outbox(directory: dir.appendingPathComponent("outbox"), phone: "ph_a")
        let take = try box.enqueue(voiceDraft("t.m4a"), to: .newTopic(workspace: "ws_abcdefghij"), joinAfter: "first")
        XCTAssertFalse(box.resolveJoins { _ in nil })
        XCTAssertNotNil(box.item(clientId: take.clientId)?.joinAfter)
        XCTAssertTrue(box.resolveJoins { $0 == "first" ? "t_known" : nil })
        let now = try XCTUnwrap(box.item(clientId: take.clientId))
        XCTAssertNil(now.joinAfter); XCTAssertEqual(now.ticket, "t_known")
    }
}
