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
        XCTAssertEqual(chips.first?.label, "Topic started")
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
        XCTAssertEqual(ConversationRules.summaryText(done: 0, total: 0, status: "Working"), "")
        XCTAssertEqual(ConversationRules.summaryText(done: 2, total: 5, status: "Working"), "2 of 5 steps done")
        XCTAssertEqual(ConversationRules.summaryText(done: 0, total: 0, status: "Ready for review"), "")
        XCTAssertEqual(ConversationRules.summaryText(done: 3, total: 3, status: "Ready for review"), "3 of 3 steps done")
        XCTAssertEqual(ConversationRules.summaryText(done: 0, total: 1, status: "Working"), "1 step")
        XCTAssertEqual(ConversationRules.summaryText(done: 1, total: 1, status: "Working"), "1 step · done")
    }

    func testFailedPictureTapRetriesInsteadOfOpening() {
        XCTAssertTrue(BlobImageState.failed.tapRetries)
        for state in [BlobImageState.loading, .loaded, .unavailable] { XCTAssertFalse(state.tapRetries) }
    }

    func testQueuedClockSaysWaitingOnlyWithoutBannerOrNote() {
        XCTAssertTrue(ReceiptView.showsWaitingWord(offline: false, note: nil), "online, not left yet: say Waiting")
        XCTAssertFalse(ReceiptView.showsWaitingWord(offline: true, note: nil), "the offline banner says it")
        XCTAssertFalse(ReceiptView.showsWaitingWord(offline: false, note: "Try again later"), "the note says it")
    }

    func testOwnBubbleStampContrast() {
        func lum(_ hex: UInt32) -> Double {
            func c(_ v: UInt32) -> Double { let x = Double(v) / 255; return x <= 0.03928 ? x / 12.92 : pow((x + 0.055) / 1.055, 2.4) }
            return 0.2126 * c(hex >> 16 & 0xff) + 0.7152 * c(hex >> 8 & 0xff) + 0.0722 * c(hex & 0xff)
        }
        let ratio = (lum(0xbfcccb) + 0.05) / (lum(0x1d5446) + 0.05)
        XCTAssertGreaterThanOrEqual(ratio, 4.5, "Theme.mineStamp on Theme.mineFill")
    }

    func testStepsRowOnlyWhenItSaysSomething() {
        XCTAssertFalse(ConversationRules.showsStepsRow(total: 0, wontDo: 0))
        XCTAssertTrue(ConversationRules.showsStepsRow(total: 1, wontDo: 0), "one step still opens the sheet")
        XCTAssertTrue(ConversationRules.showsStepsRow(total: 1, wontDo: 1), "a won't-do still needs saying")
        XCTAssertTrue(ConversationRules.showsStepsRow(total: 2, wontDo: 0))
    }

    func testQuestionsBannerOnlyWithTwoOrMore() {
        func q(_ id: String, answer: String? = nil) -> ConvItem {
            var i = ConvItem(id: id, at: "2026-11-06T10:00:00Z", side: .them, kind: .question); i.answer = answer; return i
        }
        XCTAssertNil(ConversationRules.questionsBanner(in: [q("a")]), "one card says it by itself")
        XCTAssertNil(ConversationRules.questionsBanner(in: [q("a"), q("b", answer: "Yes")]))
        XCTAssertEqual(ConversationRules.questionsBanner(in: [q("a"), q("b")]), "2 questions")
    }

    func testHeaderStatusHiddenWhenACardSaysIt() {
        XCTAssertNil(ConversationRules.headerStatus(.waitingOnYou, openQuestions: 1, reviewBar: false))
        XCTAssertEqual(ConversationRules.headerStatus(.waitingOnYou, openQuestions: 0, reviewBar: false), .waitingOnYou)
        XCTAssertNil(ConversationRules.headerStatus(.review, openQuestions: 0, reviewBar: true))
        XCTAssertEqual(ConversationRules.headerStatus(.working, openQuestions: 2, reviewBar: false), .working)
    }

    func testOneStatusColourSet() {
        XCTAssertEqual(TopicStatus.working.tone, Theme.brand)
        XCTAssertEqual(TopicStatus.waitingOnYou.tone, Theme.warn)
        XCTAssertEqual(TopicStatus.review.tone, Theme.warn)
        XCTAssertEqual(TopicStatus.done.tone, Theme.muted)
    }

    func testFreshStartDayLabel() {
        XCTAssertEqual(ConversationRules.freshStartLabel("Today"), "Today · fresh start")
    }

    func testBlobImageStates() {
        XCTAssertEqual(BlobImageState.after(data: nil, isImage: false), .failed)
        XCTAssertEqual(BlobImageState.after(data: Data([1]), isImage: false), .unavailable)
        XCTAssertEqual(BlobImageState.after(data: Data([1]), isImage: true), .loaded)
        XCTAssertEqual(BlobImageState.failed.text, "Couldn't load · Tap to try again")
    }

    func testSummaryRepeatsResultAfterTrimming() {
        let result = ConvItem(id: "r", at: "1", side: .them, text: "\n Page is ready  ", label: "Result")
        XCTAssertTrue(ConversationRules.summaryRepeatsResult("  Page is ready\n", in: [result]))
    }

    func testSummaryContainedInResult() {
        let result = ConvItem(id: "r", at: "1", side: .them, text: "Page is ready. Added a preview.", label: "Result")
        XCTAssertTrue(ConversationRules.summaryRepeatsResult("Page is ready.", in: [result]))
    }

    func testResultContainedInSummary() {
        let result = ConvItem(id: "r", at: "1", side: .them, text: "Page is ready.", label: "Result")
        XCTAssertTrue(ConversationRules.summaryRepeatsResult("Page is ready. Added a preview.", in: [result]))
    }

    func testDifferentSummaryDoesNotRepeatResult() {
        let result = ConvItem(id: "r", at: "1", side: .them, text: "Page is ready.", label: "Result")
        XCTAssertFalse(ConversationRules.summaryRepeatsResult("Fixed the login.", in: [result]))
    }

    func testSummaryRepeatsResultWithDifferentWhitespace() {
        let result = ConvItem(id: "r", at: "1", side: .them, text: "Page\n\n is\tready.  Added a preview.", label: "Result")
        XCTAssertTrue(ConversationRules.summaryRepeatsResult("Page is ready.\r\nAdded   a\tpreview.", in: [result]))
    }

    func testSummaryRepeatsResultIgnoresNonResultItems() {
        let plain = ConvItem(id: "p", at: "1", side: .them, text: "Page is ready.")
        let working = ConvItem(id: "w", at: "2", side: .them, text: "Page is ready.", label: "Working")
        XCTAssertFalse(ConversationRules.summaryRepeatsResult("Page is ready.", in: [plain, working]))
        let result = ConvItem(id: "r", at: "3", side: .them, text: "Page is ready.", label: "Result")
        XCTAssertTrue(ConversationRules.summaryRepeatsResult("Page is ready.", in: [plain, working, result]))
    }

    func testSummaryRepeatsResultIgnoresEmptyTexts() {
        let empty = ConvItem(id: "e", at: "1", side: .them, text: " \n\t", label: "Result")
        let result = ConvItem(id: "r", at: "2", side: .them, text: "Page is ready.", label: "Result")
        XCTAssertFalse(ConversationRules.summaryRepeatsResult("Page is ready.", in: [empty]))
        XCTAssertFalse(ConversationRules.summaryRepeatsResult(" \n\t", in: [result]))
        XCTAssertFalse(ConversationRules.summaryRepeatsResult("Page is ready.", in: []))
    }

    func testResultCardsMergeOnlyConsecutiveAgentResults() {
        let file = MessageAttachment(blobId: "b_html", kind: .file, name: "fish.html", size: 10, mime: "text/html")
        let first = ConvItem(id: "r1", at: "1", side: .them, text: "Page is ready", attachments: [file], label: "RESULT",
                             artifacts: [.init(blobId: "b_preview", name: "preview.png"), .init(name: "notes.txt")])
        let second = ConvItem(id: "r2", at: "2", side: .them, text: "Duplicate summary", attachments: [file], label: "RESULT",
                              artifacts: [.init(blobId: "b_html", name: "fish.html"), .init(blobId: "b_preview", name: "renamed.png"), .init(name: "notes.txt"), .init(name: "extra.txt")])
        let merged = ConversationBuilder.mergingResults([first, second], review: true)
        XCTAssertEqual(merged.count, 1)
        XCTAssertEqual(merged.first?.id, "r1")
        XCTAssertEqual(merged.first?.text, "Page is ready")
        XCTAssertEqual(merged.first?.label, "Result")
        XCTAssertEqual(merged.first?.attachments, [file])
        XCTAssertEqual(merged.first?.artifacts.map(\.name), ["preview.png", "notes.txt", "extra.txt"])
        let mine = ConvItem(id: "m", at: "2", side: .me, text: "Another request")
        let question = ConvItem(id: "q", at: "2", side: .them, kind: .question)
        let plain = ConvItem(id: "p", at: "2", side: .them, text: "One moment")
        for separator in [mine, question, plain] {
            let separate = ConversationBuilder.mergingResults([first, separator, second], review: false)
            XCTAssertEqual(separate.map(\.id), ["r1", separator.id, "r2"])
            XCTAssertEqual(separate.first?.label, "Result")
        }
    }

    func testWithoutReviewHeadline() {
        XCTAssertEqual(ConversationRules.withoutReviewHeadline("Ready for your review\nMade fish.html."), "Made fish.html.")
        XCTAssertEqual(ConversationRules.withoutReviewHeadline("ready for your review: X\nMade fish.html."), "Made fish.html.")
        XCTAssertEqual(ConversationRules.withoutReviewHeadline("Made fish.html.\nReady for your review: Fish"), "Made fish.html.\nReady for your review: Fish")
        XCTAssertEqual(ConversationRules.withoutReviewHeadline("Ready for your review: Fish"), "Ready for your review: Fish")
        XCTAssertEqual(ConversationRules.withoutReviewHeadline("Ready for your review\n"), "Ready for your review\n")
        XCTAssertEqual(ConversationRules.withoutReviewHeadline("Ready for your review: Fish\r\n\n Made fish.html. \n"), "\n Made fish.html. \n")
    }

    func testReviewTicketResultShowsStatusOnlyInHeader() {
        let text = "Ready for your review: Fish\nMade fish.html."
        let message = PhoneMessage(message: TextMessage(id: "r1", from: "ws_a", to: "ph_1", type: "text", createdAt: "2026-11-09T10:00:00Z", ticket: "t_1",
                                                       body: TextBody(text: text, update: TextUpdate(kind: "result"))), workspaceName: "A")
        let ticket = Ticket(id: "ws_a|t_1", workspace: "ws_a", workspaceName: "A", ticket: "t_1", title: "Fish", text: text,
                            status: .review, kind: "result", at: "2026-11-09T10:00:00Z", question: nil)
        let items = ConversationBuilder.items(.topic(workspace: "ws_a", ticket: "t_1"), ConversationInputs(messages: [message], tickets: [ticket]))
        XCTAssertEqual(items.count, 1)
        XCTAssertEqual(items.first?.label, "Result")
        XCTAssertEqual(items.first?.text, "Made fish.html.")
    }

    func testTicketBuilderMergesResultsAcrossHiddenWorkingUpdates() {
        func update(_ id: String, kind: String, text: String) -> PhoneMessage {
            PhoneMessage(message: TextMessage(id: id, from: "ws_a", to: "ph_1", type: "text", createdAt: "2026-11-06T10:00:0\(id)Z", ticket: "t_1",
                                              body: TextBody(text: text, update: TextUpdate(kind: kind))), workspaceName: "A")
        }
        let input = ConversationInputs(messages: [update("1", kind: "result", text: "First result"),
                                                 update("2", kind: "working", text: "Working"),
                                                 update("3", kind: "result", text: "Second result")])
        let items = ConversationBuilder.items(.topic(workspace: "ws_a", ticket: "t_1"), input)
        XCTAssertEqual(items.count, 1)
        XCTAssertEqual(items.first?.text, "First result")
        XCTAssertEqual(items.first?.label, "Result")
    }

    func testOutboxHandoffKeepsOneRowAndItsIdentity() {
        let id = ConversationID.general(workspace: "ws_a")
        var pending = OutboxItem(clientId: "c1", phone: "ph_1", kind: .send, workspace: "ws_a", createdAt: "2026-11-06T09:00:00Z")
        pending.general = true; pending.text = "Start a thing"
        var input = ConversationInputs(outbox: [pending])
        let queued = ConversationBuilder.items(id, input)
        XCTAssertEqual(queued.count, 1)
        XCTAssertEqual(queued.first?.receipt, .queued)
        pending.sentMessageId = "m1"; input.outbox = [pending]
        let sent = ConversationBuilder.items(id, input)
        XCTAssertEqual(sent.count, 1)
        XCTAssertEqual(sent.first?.receipt, .sent)
        XCTAssertEqual(sent.first?.rowID, queued.first?.rowID)
        input.messages = [general("m1")]
        let listed = ConversationBuilder.items(id, input)
        XCTAssertEqual(listed.count, 1)
        XCTAssertEqual(listed.first?.rowID, queued.first?.rowID)
        XCTAssertEqual(listed.first?.id, "m1", "replies still use the server id")
        input.outbox = []
        XCTAssertEqual(ConversationBuilder.items(id, input), listed)
        input.messages = []; pending.sentMessageId = nil; pending.failure = "Refused"; input.outbox = [pending]
        XCTAssertEqual(ConversationBuilder.items(id, input).first?.receipt, .failed("Refused"))
    }

    func testGeneralStartedChipHidesItsAckBubble() {
        let messages = [general("m1"), ack("a1", replyTo: "m1", ticket: "t_1")]
        let chips = ConversationRules.startedChips(messages: messages, workspace: "ws_a", key: { _ in nil })
        XCTAssertEqual(chips.map(\.ticket), ["t_1"])
        let items = ConversationBuilder.items(.general(workspace: "ws_a"), ConversationInputs(messages: messages))
        XCTAssertEqual(items.map(\.id), ["m1"])
        XCTAssertFalse(items.contains { $0.text == "Got it" })
        let legacy = ChatBuilder.workspaceItems("ws_a", ChatData(messages: messages))
        XCTAssertFalse(legacy.contains { if case .theirs = $0.kind { return true }; return false })
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

    /// The scripted recorder (UI tests) must not ask this phone's speech recognition: that raises a system alert and the memo bubble
    /// waits for the transcript (W7: test08 never saw its bubble).
    func testScriptedVoiceMemoNeverUsesOnDeviceSpeech() async throws {
        let m = await paired()
        let url = dir.appendingPathComponent("scripted.m4a")
        try Data("scripted-audio".utf8).write(to: url)
        let started = Date()
        let draft = await m.voiceDraft(for: VoiceSegment(url: url, duration: 2))
        XCTAssertLessThan(Date().timeIntervalSince(started), 5, "no waiting for speech permission or assets")
        XCTAssertFalse(draft.url.path.isEmpty)
        let t = m.voiceTranscriber()
        do { _ = try await t.onDevice(url, "en"); XCTFail("on-device speech must be off for scripted audio") } catch {}
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
        m.markRead(id, atBottom: false)   // scrolled up: the new message was not seen
        XCTAssertEqual(m.unread(id), 1, "stays unread while scrolled up")
        m.markRead(id)   // reaching the bottom
        XCTAssertEqual(m.unread(id), 0)
    }

    func testReadGoesOnlyUpToWhatWasShown() {
        let items: [ReadRules.Line] = [("a", "2026-11-05T10:00:00Z", true), ("b", "2026-11-05T10:01:00Z", false),
                                       ("c", "2026-11-05T10:02:00Z", true), ("d", "2026-11-05T10:03:00Z", true)]
        XCTAssertEqual(ReadRules.readUpTo(items, atBottom: true), "2026-11-05T10:03:00Z")
        XCTAssertEqual(ReadRules.readUpTo(items, atBottom: false, lastVisibleId: "c"), "2026-11-05T10:02:00Z")
        XCTAssertEqual(ReadRules.readUpTo(items, atBottom: false, lastVisibleId: "b"), "2026-11-05T10:00:00Z")
        XCTAssertNil(ReadRules.readUpTo(items, atBottom: false), "scrolled up with nothing known on screen: nothing new is read")
        XCTAssertNil(ReadRules.readUpTo(items, atBottom: false, lastVisibleId: "gone"))
    }

    func testGroupReadStopsAtLastVisibleMessage() async {
        let m = await paired()
        let items = [ChatItem(id: "g1", at: "2026-11-05T10:00:00Z", kind: .theirs("one", label: nil)),
                     ChatItem(id: "g2", at: "2026-11-05T10:01:00Z", kind: .theirs("two", label: nil))]
        m.markRead("group:x", items: items, atBottom: false, lastVisibleId: "g1")
        XCTAssertEqual(m.readState.unread("group:x", in: items), 1)
        m.markRead("group:x", items: items, atBottom: true)
        XCTAssertEqual(m.readState.unread("group:x", in: items), 0)
    }

    func testOlderPagesLoadOneAtATimeAndStopAtTheEnd() async throws {
        let m = await paired(); m.pageSize = 2
        await m.reloadMessages()
        let first = try XCTUnwrap(m.messagesNext, "more than one page in the sample")
        let running = Task { await m.loadOlderMessages() }
        await Task.yield()
        XCTAssertTrue(m.loadingOlder)
        await m.loadOlderMessages()   // a second request while one runs does nothing
        XCTAssertEqual(m.messagesNext, first)
        await running.value
        XCTAssertFalse(m.loadingOlder)
        XCTAssertNotEqual(m.messagesNext, first, "the cursor moved on")
        var guardRail = 0
        while m.hasOlderMessages && guardRail < 100 { await m.loadOlderMessages(); guardRail += 1 }
        XCTAssertNil(m.messagesNext, "stops at the end")
        let all = m.messages.count
        await m.loadOlderMessages()
        XCTAssertEqual(m.messages.count, all)
    }

    func testOlderPageFailureOffersRetry() async throws {
        let m = await paired(); m.pageSize = 2
        await m.reloadMessages()
        let cursor = try XCTUnwrap(m.messagesNext)
        await m.mock!.setOffline(true)
        await m.loadOlderMessages()
        XCTAssertTrue(m.olderFailed); XCTAssertEqual(m.messagesNext, cursor, "keeps its place for the retry")
        await m.mock!.setOffline(false)
        await m.loadOlderMessages()
        XCTAssertFalse(m.olderFailed); XCTAssertNotEqual(m.messagesNext, cursor)
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
