import XCTest
@testable import OrchMobile

@MainActor
final class ChatTests: XCTestCase {
    private func data(_ m: MockRelay, answers: [String: String] = [:], outbox: [QueuedText] = []) async throws -> ChatData {
        let u = try await m.updates(), q = try await m.questions()
        return ChatData(workspaces: try await m.workspaces(), messages: try await m.messages(),
                        tickets: TicketBuilder.build(updates: u, questions: q, answers: answers), questions: q, answers: answers, outbox: outbox)
    }

    func testSnapshotDecodesWithAndWithoutTheNewFields() throws {
        let old = #"{"id":"m_1","workspace":"ws_a","workspace_name":"A","ticket":"t_1","kind":"working","title":"T","text":"x","reply_to":null,"at":"2026-11-05T10:00:00Z"}"#
        let u0 = try JSONCoding.decoder.decode(TicketUpdate.self, from: Data(old.utf8))
        XCTAssertNil(u0.key); XCTAssertNil(u0.ticketView)
        let new = #"{"id":"m_1","workspace":"ws_a","workspace_name":"A","ticket":"t_1","key":"PIL-12","kind":"working","title":"T","text":"x","reply_to":null,"at":"2026-11-05T10:00:00Z","ticket_view":{"title":"T","running":true,"checklist":[{"text":"a","done":true},{"text":"b"}],"attachments":[{"kind":"image","title":"p.png","blob_id":"b_1"}],"history_tail":[{"who":"Claude","role":"agent","text":"hi"}],"extra":1}}"#
        let u1 = try JSONCoding.decoder.decode(TicketUpdate.self, from: Data(new.utf8))
        XCTAssertEqual(u1.key, "PIL-12")
        XCTAssertEqual(u1.ticketView?.running, true)
        XCTAssertEqual(u1.ticketView?.doneCount, 1)       // no explicit "done": counted from the checklist
        XCTAssertEqual(u1.ticketView?.checklist.map(\.done), [true, false])
        XCTAssertEqual(u1.ticketView?.attachments.first?.blobId, "b_1")
        XCTAssertEqual(u1.ticketView?.historyTail.first?.text, "hi"); XCTAssertEqual(u1.ticketView?.historyTail.first?.by, "Claude"); XCTAssertEqual(u1.ticketView?.historyTail.first?.role, "agent")
    }

    func testWorkspaceChatGroupsMyTextsSystemLinesCardsAndQuestions() async throws {
        let d = try await data(MockRelay(latency: .zero))
        let items = ChatBuilder.workspaceItems(MockRelay.pilatus, d)
        XCTAssertEqual(items.map(\.at), items.map(\.at).sorted(), "oldest first")
        XCTAssertTrue(items.contains { if case .mine(let t, false) = $0.kind { return t.hasPrefix("Can you make the Q3") }; return false })
        XCTAssertTrue(items.contains { if case .theirs(let t, _, _) = $0.kind { return t.hasPrefix("Yes, I can answer") }; return false })
        XCTAssertTrue(items.contains { if case .card(let t) = $0.kind { return t.key == "PIL-12" }; return false })
        XCTAssertTrue(items.contains { if case .question = $0.kind { return true }; return false })
        XCTAssertFalse(items.contains { if case .question(let q) = $0.kind { return q.message.from != MockRelay.pilatus }; return false }, "no other workspace's question")
    }

    func testTicketChatHasHistoryResultAttachmentsAndMyReplies() async throws {
        var d = try await data(MockRelay(latency: .zero))
        d.outbox = [QueuedText(id: "o1", workspace: MockRelay.pilatus, ticket: "t_q3sum1", text: "Please add September", at: "2026-11-06T09:00:00Z")]
        let items = ChatBuilder.ticketItems(MockRelay.pilatus, "t_q3sum1", d)
        let texts = items.compactMap { i -> String? in if case .theirs(let t, _, _) = i.kind { return t }; return nil }
        XCTAssertTrue(texts.contains("Pulled the numbers from the Q3 sheet."))
        XCTAssertTrue(items.contains { if case .theirs(_, "RESULT", _) = $0.kind { return true }; return false })
        XCTAssertEqual(items.filter { if case .attachment = $0.kind { return true }; return false }.count, 3)
        XCTAssertEqual(items.last.map { if case .mine(let t, true) = $0.kind { return t }; return "" }, "Please add September", "queued text stays last and marked")
    }

    func testHistoryTailIsLimitedToThirtyLines() {
        let lines = (0..<45).map { TicketSnapshot.Line(at: String(format: "2026-11-05T10:%02d:00Z", $0 % 60), by: "agent", text: "line \($0)") }
        let t = Ticket(id: "ws|t", workspace: "ws", workspaceName: "W", ticket: "t", title: "T", text: "x", status: .working, kind: "working", at: "2026-11-05T11:00:00Z",
                       question: nil, key: "W-1", view: TicketSnapshot(historyTail: lines))
        let items = ChatBuilder.ticketItems("ws", "t", ChatData(tickets: [t]))
        XCTAssertEqual(items.filter { if case .theirs = $0.kind { return true }; return false }.count, 30)
    }

    func testUnreadCountsIncomingOnlyAndMarkRead() async throws {
        let d = try await data(MockRelay(latency: .zero))
        var read = ReadState()
        let before = ChatBuilder.rooms(d, read: read).first { $0.workspace.id == MockRelay.pilatus }!
        XCTAssertGreaterThan(before.unread, 0)
        let items = ChatBuilder.workspaceItems(MockRelay.pilatus, d)
        XCTAssertEqual(before.unread, items.filter(\.incoming).count)
        read.markRead(ReadState.workspaceKey(MockRelay.pilatus), upTo: items.filter(\.incoming).map(\.at).max()!)
        XCTAssertEqual(ChatBuilder.rooms(d, read: read).first { $0.workspace.id == MockRelay.pilatus }!.unread, 0)
        XCTAssertGreaterThan(ChatBuilder.rooms(d, read: read).first { $0.workspace.id == MockRelay.reports }!.unread, 0, "other chats stay unread")
    }

    func testSearchFindsByKeyTitleAndMessageText() async throws {
        let d = try await data(MockRelay(latency: .zero))
        let rooms = ChatBuilder.rooms(d, read: ReadState())
        XCTAssertEqual(ChatBuilder.search("pil-12", d, rows: rooms).chats.map { $0.ticket.key }, ["PIL-12"], "typing the key finds the ticket")
        XCTAssertEqual(ChatBuilder.search("INVOICE", d, rows: rooms).chats.map { $0.ticket.key }, ["RGS-4"])
        XCTAssertTrue(ChatBuilder.search("board", d, rows: rooms).messages.contains { $0.who == "You" })
        XCTAssertEqual(ChatBuilder.search("Pilatus", d, rows: rooms).rooms.count, 1)
        XCTAssertTrue(ChatBuilder.search("zzzz", d, rows: rooms).isEmpty)
        XCTAssertTrue(ChatBuilder.search("   ", d, rows: rooms).isEmpty)
    }

    func testFiltersAndOrderPutNeedsYouFirst() async throws {
        let d = try await data(MockRelay(latency: .zero))
        let rooms = ChatBuilder.rooms(d, read: ReadState())
        XCTAssertEqual(rooms.count, 2)
        XCTAssertTrue(rooms.allSatisfy { $0.openQuestions == 1 })
        XCTAssertEqual(ChatBuilder.filtered(rooms, .needsYou).count, 2)
        var answered = d; answered.answers = Dictionary(uniqueKeysWithValues: d.questions.map { ($0.id, "x") })
        let calm = ChatBuilder.rooms(answered, read: ReadState())
        XCTAssertTrue(ChatBuilder.filtered(calm, .needsYou).allSatisfy { $0.tickets.allSatisfy { $0.ticket.status == .needsYou } })
        XCTAssertEqual(ChatBuilder.filtered(rooms, .tickets).flatMap(\.tickets).count, rooms.flatMap(\.tickets).count)
    }

    func testComposerWording() {
        XCTAssertEqual(ChatBuilder.composerNote(running: true), "Goes in after this step")
        XCTAssertEqual(ChatBuilder.composerNote(running: false), "Saved for the next run")
        XCTAssertEqual(ChatBuilder.composerNote(running: nil), "Saved for the next run")
    }

    func testUndoCancelsTheSendAndLaterSends() async throws {
        let model = AppModel(useMock: true)
        model.undoDelay = .milliseconds(150)
        let q = try await MockRelay(latency: .zero).questions().first!
        model.chooseAnswer(q, "DATE")
        XCTAssertEqual(model.pendingAnswers[q.id], "DATE")
        model.undoAnswer(q)
        XCTAssertNil(model.pendingAnswers[q.id])
        try await Task.sleep(for: .milliseconds(400))
        XCTAssertNil(model.answers[q.id], "undone: nothing sent")
        model.chooseAnswer(q, "TIMESTAMP")
        try await Task.sleep(for: .milliseconds(900))
        XCTAssertEqual(model.answers[q.id], "TIMESTAMP")
        XCTAssertNil(model.pendingAnswers[q.id])
    }

    private func pairedOffline() async -> AppModel {
        Keychain.delete(); UserDefaults.standard.removeObject(forKey: "chatOutbox")
        UserDefaults.standard.set(true, forKey: "mockFail")
        let model = AppModel(useMock: true)
        model.openSampleInvite(); await model.connect(phoneName: "Test phone"); await model.finishSetup(allowNotifications: false)
        return model
    }
    private func cleanup() { UserDefaults.standard.removeObject(forKey: "mockFail"); UserDefaults.standard.removeObject(forKey: "chatRead"); Keychain.delete() }

    func testOfflineSendIsQueuedAndKept() async throws {
        defer { cleanup() }
        let model = await pairedOffline()
        let r = await model.sendChat(to: MockRelay.pilatus, text: "  Please add the September totals  ", ticket: "t_q3sum1")
        XCTAssertEqual(r, .queued)
        XCTAssertEqual(model.outbox.map(\.text), ["Please add the September totals"])
        XCTAssertEqual(model.outbox.first?.phone, "ph_iphone0001", "tagged with the phone it was written under")
        XCTAssertEqual(AppModel(useMock: true).outbox.count, 1, "survives a restart of the same phone")
    }

    func testSignOutClearsOutboxReadStateAndUndoTimers() async throws {
        defer { cleanup() }
        let model = await pairedOffline()
        _ = await model.sendChat(to: MockRelay.pilatus, text: "waits", ticket: nil)
        model.markRead("ws:x", items: [ChatItem(id: "i", at: "2026-11-05T10:00:00Z", kind: .theirs("a", label: nil))])
        XCTAssertFalse(UserDefaults.standard.dictionary(forKey: "chatRead")?.isEmpty ?? true)
        model.undoDelay = .milliseconds(200)
        let q = MockRelayTestsFixtures.question
        model.chooseAnswer(q, "DATE")
        await model.signOut()
        XCTAssertTrue(model.outbox.isEmpty); XCTAssertTrue(model.pendingAnswers.isEmpty); XCTAssertTrue(model.sendingAnswers.isEmpty)
        XCTAssertEqual(model.readState, ReadState())
        XCTAssertNil(UserDefaults.standard.object(forKey: "chatRead")); XCTAssertNil(UserDefaults.standard.object(forKey: "chatOutbox"))
        XCTAssertTrue(AppModel(useMock: true).outbox.isEmpty, "nothing on disk for the next person")
        try await Task.sleep(for: .milliseconds(500))
        XCTAssertNil(model.answers[q.id], "the undo timer was cancelled: no answer goes out after sign-out")
    }

    func testAnotherPhonesQueuedTextIsDroppedNotSent() async throws {
        defer { cleanup() }
        var model: AppModel? = await pairedOffline()
        _ = await model?.sendChat(to: MockRelay.pilatus, text: "mine", ticket: nil)
        model = nil
        // a leftover from a different phone on the same disk
        let foreign = QueuedText(id: "f1", workspace: MockRelay.pilatus, ticket: nil, text: "not yours", at: "2026-11-06T09:00:00Z", phone: "ph_other0001")
        let mine = QueuedText(id: "m1", workspace: MockRelay.pilatus, ticket: nil, text: "mine", at: "2026-11-06T09:00:00Z", phone: "ph_iphone0001")
        let url = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0].appendingPathComponent("chat-outbox.json")
        try JSONEncoder().encode([foreign, mine]).write(to: url)
        UserDefaults.standard.removeObject(forKey: "mockFail")
        let reloaded = AppModel(useMock: true)
        XCTAssertEqual(reloaded.outbox.map(\.id), ["m1"])
    }

    func testOverlappingRefreshesSendAQueuedTextOnce() async throws {
        defer { cleanup() }
        let first = await pairedOffline()
        let r = await first.sendChat(to: MockRelay.pilatus, text: "only once", ticket: nil)
        XCTAssertEqual(r, .queued); XCTAssertEqual(first.outbox.count, 1); XCTAssertNotNil(Keychain.load())
        UserDefaults.standard.removeObject(forKey: "mockFail")
        let model = AppModel(useMock: true)      // the phone comes back online: same credentials and outbox from disk
        XCTAssertEqual(model.outbox.count, 1)
        async let a: Void = model.refresh(); async let b: Void = model.refresh(); async let c: Void = model.refresh()
        _ = await (a, b, c)
        XCTAssertTrue(model.outbox.isEmpty)
        let sent = model.messages.filter { $0.fromPhone && $0.message.body.text == "only once" }
        XCTAssertEqual(sent.count, 1)
    }

    func testThumbnailIsBounded() throws {
        let r = UIGraphicsImageRenderer(size: CGSize(width: 4000, height: 3000))
        let big = r.pngData { c in UIColor.red.setFill(); c.fill(CGRect(x: 0, y: 0, width: 4000, height: 3000)) }
        let t = try XCTUnwrap(Thumbnail.image(from: big))
        XCTAssertLessThanOrEqual(max(t.size.width * t.scale, t.size.height * t.scale), 2048)
        XCTAssertNil(Thumbnail.image(from: Data([1, 2, 3])))
    }

    func testOnlyWebLinksOpenAndImagesNeedABlob() {
        XCTAssertNotNil(SafeLink.url("https://docs.pilatus.ch/board"))
        XCTAssertNotNil(SafeLink.url("http://example.com"))
        for bad in ["tel:+41790000000", "file:///etc/passwd", "orch://pair?code=x", "javascript:alert(1)", "sms:1", "https://", "//evil.com", "", "not a url"] {
            XCTAssertNil(SafeLink.url(bad), bad)
        }
        XCTAssertEqual(SafeLink.host("https://docs.pilatus.ch/board"), "docs.pilatus.ch")
        XCTAssertTrue(BlobID.isValid("b_chart-1")); XCTAssertFalse(BlobID.isValid("../x")); XCTAssertFalse(BlobID.isValid("a/b")); XCTAssertFalse(BlobID.isValid(""))
    }

    func testBlobRequestUsesPairedCredentialsOnTheRelayOnly() async throws {
        StubProtocol.handler = { _ in (200, Data([1, 2, 3])) }
        let base = URL(string: "https://relay.severin.io")!
        let c = URLSessionRelayClient(base: base, credentials: Credentials(relay: base, phoneId: "ph_iphone0001", token: "orn_x", phoneName: "P"), session: StubProtocol.session())
        let d = try await c.blob(id: "b_chart")
        XCTAssertEqual(d.count, 3)
        let seen = StubProtocol.seen.last
        XCTAssertEqual(seen?.url?.host, "relay.severin.io"); XCTAssertEqual(seen?.url?.path, "/v1/phone/blobs/b_chart")
        XCTAssertEqual(seen?.value(forHTTPHeaderField: "X-Orch-Phone"), "ph_iphone0001")
        do { _ = try await c.blob(id: "https://evil.example/x"); XCTFail("must refuse") } catch {}
    }

    func testTimeText() {
        let now = ISO8601DateFormatter().date(from: "2026-11-06T12:00:00Z")!
        var cal = Calendar(identifier: .gregorian); cal.timeZone = TimeZone(identifier: "UTC")!
        XCTAssertEqual(ChatBuilder.timeText("2026-11-05T11:20:00Z", now: now, calendar: cal), "Yesterday")
        XCTAssertEqual(ChatBuilder.timeText("2026-11-01T11:20:00Z", now: now, calendar: cal).isEmpty, false)
    }

    /// An image shows its proof title ("Q3 chart"), like files and links; the file name only without one.
    func testLinkAttachmentCarriesTypeIconAndStatus() throws {
        let json = #"{"kind":"link","title":"Add CSV export","url":"https://github.com/acme/billing/pull/418","at":"2026-11-06T09:38:00Z","label":"GitHub · Pull request","icon":"github","mono":"GH","status":"review"}"#
        let a = try JSONDecoder().decode(TicketSnapshot.Attachment.self, from: Data(json.utf8))
        XCTAssertEqual([a.linkType, a.icon, a.mono, a.status], ["GitHub · Pull request", "github", "GH", "review"])
        XCTAssertEqual(a.label, "Add CSV export")  // the person reads the title, not the type
        let old = try JSONDecoder().decode(TicketSnapshot.Attachment.self, from: Data(#"{"kind":"link","title":"x","url":"https://a.example","at":"2026-11-06T09:38:00Z"}"#.utf8))
        XCTAssertNil(old.linkType); XCTAssertNil(old.status)
    }

    func testAttachmentLabelPrefersTheTitle() {
        XCTAssertEqual(TicketSnapshot.Attachment(kind: "image", title: "Q3 chart", name: "bright.png").label, "Q3 chart")
        XCTAssertEqual(TicketSnapshot.Attachment(kind: "image", name: "bright.png").label, "bright.png")
        XCTAssertEqual(TicketSnapshot.Attachment(kind: "image").label, nil)
    }

    func testLinkCardAlwaysShowsTheRealHostAndNoBorrowedSiteIcon() {
        let evil = "https://evil.example/acme/pull/1"
        XCTAssertEqual(LinkFace.subtitle(type: "GitHub PR", url: evil), "GitHub PR · evil.example")
        XCTAssertEqual(LinkFace.icon("github", url: evil), "link")
        XCTAssertEqual(LinkFace.icon("github", url: "https://github.com.evil.example/x"), "link")
        XCTAssertEqual(LinkFace.icon("github", url: "https://www.github.com/a/b/pull/1"), "github")
        XCTAssertEqual(LinkFace.icon("jira", url: "https://acme.atlassian.net/browse/X-1"), "jira")
        XCTAssertEqual(LinkFace.subtitle(type: "GitHub · Pull request", url: "https://github.com/a/b/pull/1"), "GitHub · Pull request · github.com")
        XCTAssertEqual(LinkFace.subtitle(type: nil, url: evil), "evil.example")
    }
}
