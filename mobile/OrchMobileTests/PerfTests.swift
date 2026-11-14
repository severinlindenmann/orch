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
}
