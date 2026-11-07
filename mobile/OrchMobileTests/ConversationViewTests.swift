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

    func testTopicStartedFromGeneralShowsTheOriginatingTextAndTheReply() {
        var reply = PhoneMessage(message: TextMessage(id: "r1", from: "ws_a", to: "ph_1", type: "text", createdAt: "2026-11-06T10:05:00Z", ticket: nil,
                                                      body: TextBody(text: "Plan is ready"), replyTo: "m1"), workspaceName: "A")
        var d = ConversationInputs(); d.messages = [general("m1"), ack("a1", replyTo: "m1", ticket: "t_1"), reply]
        let topic = ConversationBuilder.items(.topic(workspace: "ws_a", ticket: "t_1"), d)
        XCTAssertEqual(topic.map(\.id), ["m1", "r1"], "the text that started the topic comes first, then the agent's answer")
        let gen = ConversationBuilder.items(.general(workspace: "ws_a"), d)
        XCTAssertEqual(gen.map(\.id), ["m1"], "General keeps the text (and the chip); the answer lives in the topic")
        reply = PhoneMessage(message: TextMessage(id: "r2", from: "ws_a", to: "ph_1", type: "text", createdAt: "2026-11-06T10:06:00Z", ticket: nil,
                                                  body: TextBody(text: "Unrelated", general: true)), workspaceName: "A")
        d.messages.append(reply)
        XCTAssertFalse(ConversationBuilder.items(.topic(workspace: "ws_a", ticket: "t_1"), d).contains { $0.id == "r2" })
    }

    func testStartedChipsOnePerAckOnlyForGeneralTexts() {
        let msgs = [general("m1"), ack("a1", replyTo: "m1", ticket: "t_1"), ack("a1", replyTo: "m1", ticket: "t_1"),
                    ack("a22", replyTo: "m_topic", ticket: "t_2"), ack("a333", replyTo: "m1", ticket: nil)]
        let chips = ConversationRules.startedChips(messages: msgs, workspace: "ws_a", key: { _ in nil })
        XCTAssertEqual(chips.map(\.id), ["a1"], "duplicate ack id shown once; acks of topic texts and acks without a ticket never")
        XCTAssertEqual(chips.first?.label, "PIL-15 started")
        XCTAssertEqual(chips.first?.ticket, "t_1")
    }

    func testStartedChipNeverSitsAboveTheMessageItAnswers() {
        // The ack's clock is earlier than the phone message's (clock skew): the chip still sorts at the message's time.
        var early = ack("a1", replyTo: "m1", ticket: "t_1")
        early = PhoneMessage(message: TextMessage(id: "a1", from: "ws_a", to: "ph_1", type: "text", createdAt: "2026-11-06T08:00:00Z", ticket: "t_1",
                                                  body: early.message.body, key: "PIL-15", replyTo: "m1"), workspaceName: "A")
        let chips = ConversationRules.startedChips(messages: [general("m1"), early], workspace: "ws_a", key: { _ in nil })
        XCTAssertEqual(chips.first?.at, "2026-11-06T09:00:00Z")
    }

    func testTopicSummaryHidesTheCountWithoutAChecklist() {
        XCTAssertEqual(ConversationRules.summaryText(done: 0, total: 0, status: "Working"), "Working")
        XCTAssertEqual(ConversationRules.summaryText(done: 2, total: 5, status: "Working"), "2 of 5 · Working")
    }

    func testPresenceLineIsLowercaseExceptTheMonth() {
        var cal = Calendar(identifier: .gregorian); cal.timeZone = TimeZone(identifier: "UTC")!
        let now = ISO8601DateFormatter().date(from: "2026-11-07T10:00:00Z")!
        XCTAssertEqual(Presence.of(lastSeen: "2026-11-04T10:41:00Z", now: now).line(now: now, calendar: cal), "last seen 4 Nov")
        XCTAssertEqual(Presence.of(lastSeen: "2026-11-07T09:58:00Z", now: now).line(now: now, calendar: cal), "online")
        // "online" expires without a refresh: the same last-seen time, six minutes later.
        let later = now.addingTimeInterval(6 * 60)
        XCTAssertEqual(Presence.of(lastSeen: "2026-11-07T09:58:00Z", now: later).line(now: later, calendar: cal), "last seen 09:58")
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

    func testColdStartLandsOnTheChatsList() async throws {
        let m = await paired()
        m.path = [.workspace(MockRelay.pilatus), .general(MockRelay.pilatus)]
        await m.seedIfRequested()
        XCTAssertEqual(m.path, [], "no leftover place inside a workspace after a cold start")
    }

    func testEmptyOpenChatKeepsPolling() async throws {
        let m = await paired()
        m.watchInMock = true
        let watcher = Task { await m.watchWhileOpen(every: .milliseconds(30)) }
        await m.mock!.deliverText(from: MockRelay.reports, text: "hello from a quiet chat")
        for _ in 0..<60 where !m.messages.contains(where: { $0.message.body.text == "hello from a quiet chat" }) { try await Task.sleep(for: .milliseconds(50)) }
        watcher.cancel()
        XCTAssertTrue(m.messages.contains { $0.message.body.text == "hello from a quiet chat" }, "the poll picked it up without any user action")
    }
}


final class AudioLengthTests: XCTestCase {
    private var tone: URL { Bundle(for: BundleToken.self).url(forResource: "tone", withExtension: "m4a")! }

    func testRealM4aHasItsLengthNeverZero() async throws {
        let fromFile = await AudioLength.seconds(of: tone)
        let fromData = await AudioLength.seconds(of: try Data(contentsOf: tone))
        XCTAssertEqual(try XCTUnwrap(fromFile), 1.5, accuracy: 0.2)
        XCTAssertEqual(try XCTUnwrap(fromData), 1.5, accuracy: 0.2)
        XCTAssertEqual(voiceDurationLabel(try XCTUnwrap(fromFile)), "00:01")
    }

    func testUnknownLengthShowsNothing() async {
        let none = await AudioLength.seconds(of: Data())
        XCTAssertNil(none)
        XCTAssertNil(voiceDurationLabel(0), "no 00:00 until the length is known")
    }
}
