import XCTest
@testable import OrchMobile

final class ConversationViewTests: XCTestCase {
    func testClockTextHasTwoDigitMinutes() {
        XCTAssertEqual(clockText(1), "00:01")
        XCTAssertEqual(clockText(5.9), "00:05")
        XCTAssertEqual(clockText(90), "01:30")
        XCTAssertEqual(clockText(-3), "00:00")
        XCTAssertEqual(clockText(.nan), "00:00")
    }

    private func memo(_ id: String, lang: String) -> ConvItem {
        var i = ConvItem(id: id, at: "2026-11-06T10:00:0\(id.count)Z", side: .me)
        i.voice = VoiceMemo(blobId: "b_" + id, transcript: "x", lang: lang, langSource: .detected)
        return i
    }

    func testConversationLanguageIsTheMostUsedMemoLanguage() {
        let items = [memo("a", lang: "de"), memo("bb", lang: "en"), memo("ccc", lang: "de")]
        XCTAssertEqual(LanguageLabel.conversationLanguage(items, fallback: "fr"), "de")
        XCTAssertEqual(LanguageLabel.conversationLanguage([], fallback: "fr"), "fr")
        XCTAssertNil(LanguageLabel.label(memo: "de", conversation: "de"), "no label when it matches")
        XCTAssertEqual(LanguageLabel.label(memo: "en", conversation: "de"), "EN")
    }

    func testStaleRule() {
        func q(_ id: String, answer: String? = nil) -> ConvItem {
            var i = ConvItem(id: id, at: "2026-11-06T10:00:00Z", side: .them, kind: .question); i.answer = answer; return i
        }
        var result = ConvItem(id: "r", at: "2026-11-06T11:00:00Z", side: .them); result.label = "RESULT"
        let plain = ConvItem(id: "p", at: "2026-11-06T11:00:00Z", side: .them, text: "hello")
        XCTAssertTrue(ConversationRules.isStale(index: 0, in: [q("q"), result]), "open question, a result came after")
        XCTAssertFalse(ConversationRules.isStale(index: 0, in: [q("q"), plain]), "a plain text does not close it")
        XCTAssertFalse(ConversationRules.isStale(index: 0, in: [q("q", answer: "Yes"), result]), "answered questions are not stale")
        XCTAssertFalse(ConversationRules.isStale(index: 1, in: [result, q("q")]), "a result before it does not count")
    }

    private func ack(_ id: String, replyTo: String, ticket: String?, key: String? = "PIL-15") -> PhoneMessage {
        PhoneMessage(message: TextMessage(id: id, from: "ws_a", to: "ph_1", type: "text", createdAt: "2026-11-06T10:00:0\(id.count)Z", ticket: ticket,
                                          body: TextBody(text: "Got it", update: TextUpdate(kind: "ack"), general: true), key: key, replyTo: replyTo), workspaceName: "A")
    }
    private func general(_ id: String) -> PhoneMessage {
        PhoneMessage(message: TextMessage(id: id, from: "ph_1", to: "ws_a", type: "text", createdAt: "2026-11-06T09:00:00Z", ticket: nil,
                                          body: TextBody(text: "Start a thing", general: true)), workspaceName: "A", clientId: "c1")
    }

    func testStartedChipsOnePerAckOnlyForGeneralTexts() {
        let msgs = [general("m1"), ack("a1", replyTo: "m1", ticket: "t_1"), ack("a1", replyTo: "m1", ticket: "t_1"),
                    ack("a22", replyTo: "m_topic", ticket: "t_2"), ack("a333", replyTo: "m1", ticket: nil)]
        let chips = ConversationRules.startedChips(messages: msgs, workspace: "ws_a", key: { _ in nil })
        XCTAssertEqual(chips.map(\.id), ["a1"], "duplicate ack id shown once; acks of topic texts and acks without a ticket never")
        XCTAssertEqual(chips.first?.label, "PIL-15 started")
        XCTAssertEqual(chips.first?.ticket, "t_1")
    }

    func testThrottleNoteOnlyWhileWaiting() {
        var o = OutboxItem(clientId: "c", phone: "p", kind: .send, workspace: "w", createdAt: "2026-11-06T10:00:00Z")
        XCTAssertNil(ThrottleNote.text(for: o))
        o.throttleCount = 1
        XCTAssertEqual(ThrottleNote.text(for: o), "Try again later")
        o.sentMessageId = "m"
        XCTAssertNil(ThrottleNote.text(for: o), "sent: no note")
    }
}

@MainActor
final class ConversationModelTests: XCTestCase {
    var dir: URL!
    override func setUp() async throws { Keychain.delete(); dir = FileManager.default.temporaryDirectory.appendingPathComponent("m2-" + UUID().uuidString); UserDefaults.standard.removeObject(forKey: "chatRead") }
    override func tearDown() async throws { Keychain.delete(); try? FileManager.default.removeItem(at: dir); UserDefaults.standard.removeObject(forKey: "chatRead") }
    private func paired() async -> AppModel {
        let m = AppModel(useMock: true, voiceMode: .scripted, outboxDirectory: dir, speechCache: dir.appendingPathComponent("sp"), systemAudioControls: false)
        m.openSampleInvite(); await m.connect(phoneName: "T"); await m.finishSetup(allowNotifications: false); return m
    }

    func testThrottledSendShowsTryAgainLater() async throws {
        let m = await paired()
        await m.mock!.queueSendFailures([429])
        _ = try await m.send(MessageDraft(text: "slow down"), to: .general(workspace: MockRelay.pilatus))
        let waiting = m.outbox.items.first { $0.text == "slow down" }
        XCTAssertEqual(ThrottleNote.text(for: waiting), "Try again later")
        XCTAssertEqual(m.conversationItems(.general(workspace: MockRelay.pilatus)).last?.receipt, .queued)
    }

    func testOpenConversationStaysReadWhenNewMessagesArrive() async throws {
        let m = await paired()
        let id = ConversationID.general(workspace: MockRelay.pilatus)
        m.markRead(id); XCTAssertEqual(m.unread(id), 0)
        await m.mock!.deliverText(from: MockRelay.pilatus, text: "new while open")
        await m.refresh()
        XCTAssertEqual(m.unread(id), 1, "arrives unread")
        m.markRead(id)   // what the open screen does on every new item
        XCTAssertEqual(m.unread(id), 0)
    }

    func testEmptyOpenChatKeepsPolling() async throws {
        let m = await paired()
        let watcher = Task { await m.watchWhileOpen(every: .milliseconds(30)) }
        await m.mock!.deliverText(from: MockRelay.reports, text: "hello from a quiet chat")
        for _ in 0..<60 where !m.messages.contains(where: { $0.message.body.text == "hello from a quiet chat" }) { try await Task.sleep(for: .milliseconds(50)) }
        watcher.cancel()
        XCTAssertTrue(m.messages.contains { $0.message.body.text == "hello from a quiet chat" }, "the poll picked it up without any user action")
    }
}
