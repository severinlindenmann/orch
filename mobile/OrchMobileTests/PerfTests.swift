import XCTest
@testable import OrchMobile

/// Tap-lag measurements (phone-perf, owner point C). Each measurement prints one line "PERF <name> <ms>" (best of 5);
/// nothing asserts a timing (CI machines vary). The only assertions are the rebuild-count invariants of the derived-data cache.
@MainActor
final class PerfTests: XCTestCase {
    private struct Page<T: Encodable>: Encodable { let items: [T]; let next: String? }

    private static let workspaceCount = 6, topicsPerWorkspace = 25, messageCount = 600, questionCount = 20

    private func iso(_ n: Int) -> String {
        let d = Date(timeIntervalSince1970: 1_790_000_000 + Double(n) * 60)
        return ISO8601DateFormatter().string(from: d)
    }

    private func synthetic() -> (workspaces: [Workspace], messages: [PhoneMessage], questions: [Question]) {
        let ws = (0..<Self.workspaceCount).map {
            Workspace(id: "ws_perf\($0)", name: "Perf workspace \($0)", description: nil, tags: [], online: true, lastSeen: iso(0), openQuestions: 3)
        }
        var msgs: [PhoneMessage] = []
        for n in 0..<Self.messageCount {
            let w = ws[n % ws.count], ticket = "t_\(w.id)_\((n / ws.count) % Self.topicsPerWorkspace)"
            let fromPhone = n % 5 == 0
            let body = TextBody(text: "Message \(n) about the quarterly numbers and the board deck", clientId: fromPhone ? "c\(n)" : nil)
            msgs.append(PhoneMessage(message: TextMessage(id: "m_perf\(n)", from: fromPhone ? "ph_perf01" : w.id, to: fromPhone ? w.id : "ph_perf01",
                                                          type: "text", createdAt: iso(n), ticket: ticket, body: body, key: "PF-\(n % 90)"),
                                     workspaceName: w.name, deliveredAt: fromPhone ? iso(n) : nil, clientId: fromPhone ? "c\(n)" : nil))
        }
        let qs = (0..<Self.questionCount).map { i -> Question in
            let w = ws[i % ws.count]
            return Question(message: QuestionMessage(schema: "orch.msg/1", id: "m_perfq\(i)", from: w.id, to: "phones", type: "question",
                                                     createdAt: iso(Self.messageCount + i), ticket: "t_\(w.id)_\(i % Self.topicsPerWorkspace)",
                                                     body: QuestionBody(questionId: "q\(i)", title: "Question \(i)", text: "Which one?",
                                                                        options: ["A", "B"], recommended: "A"), key: "PF-\(i)"),
                            workspaceName: w.name)
        }
        return (ws, msgs, qs)
    }

    private func loadedModel() async -> AppModel {
        let c = Credentials(relay: URL(string: "https://relay.test")!, phoneId: "ph_perf01", token: "orn_perf", phoneName: "Test")
        Keychain.save(c)
        let s = synthetic()
        let enc = JSONCoding.encoder
        let wsJSON = try! enc.encode(Page(items: s.workspaces, next: nil))
        let qJSON = try! enc.encode(Page(items: s.questions, next: nil))
        let emptyJSON = Data(#"{"items":[]}"#.utf8)
        let box = MessageBox(s.messages.sorted { $0.message.createdAt > $1.message.createdAt })
        StubProtocol.handler = { req in
            switch req.url?.path {
            case "/v1/phone/workspaces": return (200, wsJSON)
            case "/v1/phone/questions": return (200, qJSON)
            case "/v1/phone/messages": return (200, box.json)
            case "/v1/phone/settings": return (200, try! enc.encode(PhoneSettings()))
            default: return (200, emptyJSON)
            }
        }
        let m = AppModel(useMock: false, session: StubProtocol.session())
        m.pageSize = 1000
        await m.refresh()
        currentBox = box
        return m
    }
    private final class MessageBox: @unchecked Sendable {
        var items: [PhoneMessage] { didSet { json = try! JSONCoding.encoder.encode(Page(items: items, next: nil)) } }
        private(set) var json: Data
        init(_ i: [PhoneMessage]) { items = i; json = try! JSONCoding.encoder.encode(Page(items: i, next: nil)) }
    }
    private var currentBox: MessageBox?

    override func tearDown() async throws { Keychain.delete(); StubProtocol.handler = nil }

    /// Best of 5, in ms; prints "PERF <name> <ms>".
    @discardableResult
    private func timed(_ name: String, _ body: () -> Void) -> Double {
        var best = Double.infinity
        for _ in 0..<5 {
            let t = ContinuousClock().measure(body)
            best = min(best, Double(t.components.seconds) * 1000 + Double(t.components.attoseconds) / 1e15)
        }
        print(String(format: "PERF %@ %.2f", name, best))
        return best
    }

    /// What one Chats list body reads (ChatsListView): summaries x4, the archived count, the inputs.
    private func chatsListBody(_ m: AppModel) {
        for _ in 0..<4 { _ = m.workspaceSummaries }
        _ = m.archivedCount
        _ = m.conversationInputs
    }

    func testBaselineSyntheticState() async throws {
        let m = await loadedModel()
        XCTAssertEqual(m.messages.count, Self.messageCount)
        XCTAssertEqual(m.workspaces.count, Self.workspaceCount)
        let summaries = m.workspaceSummaries
        XCTAssertFalse(summaries.isEmpty)

        timed("a_chats_list_body_reads", { chatsListBody(m) })

        let topic = summaries.flatMap(\.topics).max { $0.lastAt ?? "" < $1.lastAt ?? "" }!.id
        timed("b_open_topic_resolve_items_split") {
            let id = m.resolve(topic)
            let items = m.conversationItems(id)
            _ = ChatDay.split(items, today: ChatDay.key(for: Date()))
        }

        // c) one new message arrives: merge into 600, then what the list reads again.
        var n = 0
        let box = currentBox!
        var best = Double.infinity
        for _ in 0..<5 {
            n += 1
            let new = PhoneMessage(message: TextMessage(id: "m_new\(n)", from: "ws_perf0", to: "ph_perf01", type: "text", createdAt: iso(10_000 + n),
                                                       ticket: "t_ws_perf0_0", body: TextBody(text: "New \(n)")), workspaceName: "Perf workspace 0")
            box.items.insert(new, at: 0)
            let t0 = ContinuousClock.now
            await m.reloadMessages()
            chatsListBody(m)
            let d = ContinuousClock.now - t0
            best = min(best, Double(d.components.seconds) * 1000 + Double(d.components.attoseconds) / 1e15)
        }
        print(String(format: "PERF c_message_arrives_merge_plus_reads %.2f", best))
    }

    /// Step 3: what the Chats list formats per row (time text, last seen, relative text) for 600 rows.
    func testFormatterCost() {
        let isos = (0..<600).map { iso($0) }
        let now = Date(timeIntervalSince1970: 1_790_000_000 + 600 * 60)
        timed("d_format_600_rows") {
            for s in isos { _ = ChatBuilder.timeText(s, now: now); _ = ShellTime.short(s, now: now); _ = lastSeenText(s, online: false, now: now) }
        }
        XCTAssertFalse(ShellTime.short("2026-11-11T14:02:30.250Z", now: now).isEmpty, "fractional seconds still parse")
    }

    /// Step 4: avatars, presence lines and group rows share one clock instead of one TimelineView each.
    func testMinuteClockIsShared() {
        XCTAssertTrue(MinuteClock.shared === MinuteClock.shared)
        XCTAssertLessThan(abs(MinuteClock.shared.now.timeIntervalSinceNow), 3600 * 24)
    }

    /// Step 5: pictures decode off the main actor at <= 600 px and are remembered per blob id.
    func testInlineThumbnailIsBoundedAndCached() async throws {
        Thumbnail.evictAll()
        let renderer = UIGraphicsImageRenderer(size: CGSize(width: 3000, height: 2000))
        let data = renderer.jpegData(withCompressionQuality: 0.8) { ctx in UIColor.red.setFill(); ctx.fill(CGRect(x: 0, y: 0, width: 3000, height: 2000)) }
        XCTAssertNil(Thumbnail.cached(id: "blob_perf"))
        let first = await Thumbnail.decoded(id: "blob_perf", data: data)
        let image = try XCTUnwrap(first)
        XCTAssertLessThanOrEqual(max(image.size.width, image.size.height) * image.scale, 600)
        XCTAssertTrue(Thumbnail.cached(id: "blob_perf") === image, "the second look is a cache hit, no decode")
        let again = await Thumbnail.decoded(id: "blob_perf", data: Data())
        XCTAssertTrue(again === image, "a hit needs no bytes")
        let b = ContinuousClock().measure { for _ in 0..<5 { _ = Thumbnail.image(from: data) } }
        print("PERF e_decode_3000px_to_2048_x5 \(b)")
        let c = ContinuousClock().measure { for _ in 0..<5 { _ = Thumbnail.image(from: data, maxPixel: 600) } }
        print("PERF e_decode_3000px_to_600_x5 \(c)")
    }

    /// Step 6: the merge is incremental. A poll with nothing new changes nothing; new ones land in order; a changed copy replaces the old one.
    func testMergeIsIncrementalAndKeepsOrder() async throws {
        let m = await loadedModel()
        let box = currentBox!
        let base = m.derivedRebuilds
        let sorted0 = m.messages.map(\.id)
        await m.reloadMessages()
        XCTAssertEqual(m.messages.map(\.id), sorted0, "same page again: same list")
        XCTAssertEqual(m.derivedRebuilds, base, "nothing new: nothing rebuilt")
        // an old message arrives late (older than most) plus a new one on top
        let old = PhoneMessage(message: TextMessage(id: "m_late", from: "ws_perf0", to: "ph_perf01", type: "text", createdAt: iso(300) ,
                                                   ticket: "t_ws_perf0_0", body: TextBody(text: "Late")), workspaceName: "Perf workspace 0")
        let new = PhoneMessage(message: TextMessage(id: "m_top", from: "ws_perf0", to: "ph_perf01", type: "text", createdAt: iso(30_000),
                                                   ticket: "t_ws_perf0_0", body: TextBody(text: "Top")), workspaceName: "Perf workspace 0")
        box.items.insert(contentsOf: [new, old], at: 0)
        await m.reloadMessages()
        XCTAssertEqual(m.messages.count, Self.messageCount + 2)
        XCTAssertEqual(m.messages.first?.id, "m_top")
        let keys = m.messages.map { ($0.message.createdAt, $0.id) }
        XCTAssertTrue(zip(keys, keys.dropFirst()).allSatisfy { $0 > $1 }, "still newest first")
        XCTAssertTrue(m.messages.contains { $0.id == "m_late" })
        XCTAssertEqual(Set(m.messages.map(\.id)).count, m.messages.count, "no duplicates")
    }

    /// Step 6: the queue is in memory at once, the file follows on a background queue; the last state wins.
    func testOutboxWritesAreCoalescedAndLandOnDisk() async throws {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("perf-outbox-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: dir) }
        let ob = Outbox(directory: dir, phone: "ph_iphone0001")
        var last: OutboxItem?
        let ms = Double(ContinuousClock().measure {
            for i in 0..<50 { last = try? ob.enqueue(MessageDraft(text: "msg \(i)"), to: .general(workspace: "ws_pilatus001")) }
        }.components.attoseconds) / 1e15
        print(String(format: "PERF f_outbox_50_enqueues %.2f", ms))
        XCTAssertEqual(ob.items.count, 50, "in memory at once")
        ob.flushWrites()
        let again = Outbox(directory: dir, phone: "ph_iphone0001")
        XCTAssertEqual(again.items.count, 50)
        XCTAssertEqual(again.items.last?.clientId, last?.clientId)
        XCTAssertNil(ob.lastSaveError)
    }

    func testDerivedDataIsRebuiltOnlyWhenAnInputChanges() async throws {
        let m = await loadedModel()
        _ = m.workspaceSummaries
        let base = m.derivedRebuilds
        for _ in 0..<4 { _ = m.workspaceSummaries }
        _ = m.conversationInputs; _ = m.archivedCount; _ = m.tickets; _ = m.chatRooms
        XCTAssertEqual(m.derivedRebuilds, base, "reads with no change in between rebuild nothing")
        let before = m.workspaceSummaries
        let box = currentBox!
        box.items.insert(PhoneMessage(message: TextMessage(id: "m_arrive", from: "ws_perf0", to: "ph_perf01", type: "text", createdAt: iso(20_000),
                                                           ticket: "t_ws_perf0_0", body: TextBody(text: "Arrived")), workspaceName: "Perf workspace 0"), at: 0)
        await m.reloadMessages()
        for _ in 0..<4 { _ = m.workspaceSummaries }
        XCTAssertEqual(m.derivedRebuilds, base + 1, "a new message = exactly one more rebuild on the next read")
        XCTAssertNotEqual(m.workspaceSummaries, before, "and the rebuilt summaries show it")
        m.markRead(.general(workspace: "ws_perf0"))
        _ = m.workspaceSummaries; _ = m.workspaceSummaries
        XCTAssertLessThanOrEqual(m.derivedRebuilds, base + 2, "a read-state change is one more rebuild at most")
    }
}
