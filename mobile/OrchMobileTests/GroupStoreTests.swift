import XCTest
@testable import OrchMobile

final class GroupStoreTests: XCTestCase {
    private let finance = "ws_fin0000001", home = "ws_hom0000001", bank = "ws_ban0000001"
    private let phone = "ph_own0000001"
    private var workspaces: [String: String] { [finance: "Finance", home: "Home", bank: "Bank"] }
    private var members: [GroupMember] { [GroupMember(ws: finance, name: "Finance"), GroupMember(ws: home, name: "Home")] }

    private func vector(_ name: String, to: String? = nil) throws -> PhoneMessage {
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        let data = try Data(contentsOf: root.appendingPathComponent("contracts/vectors/chat-groups/\(name).json"))
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        var message = try XCTUnwrap(object["message"] as? [String: Any])
        if let to { message["to"] = to }
        let decoded = try JSONCoding.decoder.decode(TextMessage.self, from: JSONSerialization.data(withJSONObject: message))
        return PhoneMessage(message: decoded, workspaceName: workspaces[decoded.from] ?? "Unknown")
    }

    private func message(_ id: String, seq: Int? = 1, at: String = "10", host: String? = nil,
                         from: String? = nil, to: String = "phones", ticket: String? = "t_fin14a", edit: (inout TextBody) -> Void = { _ in }) -> PhoneMessage {
        let host = host ?? finance
        var body = TextBody(text: id, group: GroupInfo(id: "grp_t_fin14a", host: host, title: "Tax", members: members, seq: seq))
        edit(&body)
        return PhoneMessage(message: TextMessage(id: id, from: from ?? host, to: to, type: "text", createdAt: at,
            ticket: ticket, body: body, key: "FIN-14"), workspaceName: workspaces[host] ?? "Unknown")
    }

    /// Fixtures are written oldest first for readability; the phone API supplies newest first.
    private func build(_ oldestFirst: [PhoneMessage], own: Set<String> = [],
                       receivedAt: [String: Date] = [:], arrival: [String: Int] = [:], now: Date = Date(timeIntervalSince1970: 1000)) -> GroupSnapshot {
        let times = Dictionary(oldestFirst.map { ($0.id, receivedAt[$0.id] ?? Date(timeIntervalSince1970: 0)) },
                               uniquingKeysWith: { first, _ in first })
        return GroupStore.build(messages: oldestFirst.reversed(), workspaces: workspaces, ownPhoneId: phone,
                                ownMessageIds: own, receivedAt: times, arrival: arrival, now: now)
    }
    private func group(_ messages: [PhoneMessage]) throws -> PhoneGroup { try XCTUnwrap(build(messages).groups.first) }

    func testPhoneVectors() throws {
        for name in ["valid-chat-helper-text", "valid-phone-text-optin-reply", "valid-phone-text-no-optin-stays-private"] {
            let m = try vector(name)
            XCTAssertNil(m.message.body.group, name)
            XCTAssertEqual(build([m]), GroupSnapshot(groups: [], dropped: []), name)
        }
        for name in ["valid-group-created", "valid-member-added-from-seq", "valid-fanout-phones-quiet", "valid-phone-copy-with-file"] {
            let m = try vector(name)
            XCTAssertNil(GroupStore.accept(m, workspaces: workspaces), name)
            XCTAssertEqual(build([m]).groups.first?.messages.count, 1, name)
            XCTAssertTrue(build([m]).dropped.isEmpty, name)
        }
        let created = try group([vector("valid-group-created")])
        XCTAssertTrue(created.startedHere)
        XCTAssertEqual(created.members.first?.look, GroupLook(icon: "bank", color: "teal"))
        let added = try group([vector("valid-member-added-from-seq")])
        XCTAssertEqual(added.messages.first?.event?.fromSeq, 5)
        XCTAssertEqual(added.members.last?.name, "Bank")
        XCTAssertEqual(added.gaps, [])
        let joined = try group([vector("valid-group-created"), vector("valid-member-added-from-seq")])
        XCTAssertEqual(joined.gaps, [2..<5]) // Phones do not begin at a member's from_seq.
        let quiet = try group([vector("valid-fanout-phones-quiet")])
        XCTAssertEqual(quiet.messages.first?.sender, .member(home))
        XCTAssertEqual(quiet.messages.first?.quiet, true)
        XCTAssertNil(quiet.lastLine)
        let file = try group([vector("valid-phone-copy-with-file")])
        XCTAssertEqual(file.messages.first?.sharedFiles, ["b_bill2027pdf00001"])
        XCTAssertEqual(file.messages.first?.ticketView?.attachments.first?.blobId, "b_bill2027pdf00001")
        XCTAssertEqual(file.messages.first?.message.message.body.toPerson, true)

        let cases = [("invalid-copy-you-not-from-phone", "G4"), ("invalid-too-many-members", "limit"),
                     ("invalid-group-id-not-host-ticket", "G1"),
                     ("invalid-group-event-from-member", "G3"), ("invalid-member-speaks-as-you", "G3")]
        for (name, rule) in cases {
            let m = try vector(name, to: "phones")
            XCTAssertEqual(GroupStore.accept(m, workspaces: workspaces)?.rule, rule, name)
            XCTAssertEqual(build([m]).dropped.map(\.rule), [rule], name)
            XCTAssertTrue(build([m]).groups.isEmpty, name)
        }
        // Push-set enforcement belongs to the host; the phone cannot infer the host's push decision.
        let loud = try vector("invalid-phones-copy-loud")
        XCTAssertNil(GroupStore.accept(loud, workspaces: workspaces))
        XCTAssertEqual(try group([loud]).lastLine, "Home: Found it.")
    }

    func testSameGroupIdIsIndependentAcrossHosts() throws {
        let first = message("same", seq: 1) {
            $0.groupEvent = GroupEvent(kind: "closed")
            $0.task = GroupTask(delegate: "d", ws: self.home, status: "done")
            $0.origin = GroupOrigin(id: "origin", from: self.finance, at: "09")
        }
        let second = message("same", seq: 2, host: home) {
            $0.task = GroupTask(delegate: "d", ws: self.home, status: "working")
            $0.origin = GroupOrigin(id: "origin", from: self.home, at: "09")
        }
        for input in [[first, second], [second, first]] {
            let snapshot = build(input)
            XCTAssertEqual(Set(snapshot.groups.map(\.key)), [GroupKey(host: finance, id: "grp_t_fin14a"), GroupKey(host: home, id: "grp_t_fin14a")])
            XCTAssertEqual(Set(snapshot.groups.map(\.id)), Set(snapshot.groups.map(\.key)))
            XCTAssertEqual(Set(snapshot.groups.map { GroupListRow.rowID($0) }).count, 2)
            XCTAssertTrue(snapshot.dropped.isEmpty)
            XCTAssertEqual(snapshot.groups.first { $0.key.host == finance }?.closed, true)
            XCTAssertEqual(snapshot.groups.first { $0.key.host == home }?.tasks["d"]?.status, "working")
        }
        let invalid = message("bad", host: finance) { $0.by = "you" }
        XCTAssertEqual(build([invalid, second]).groups.first?.key.host, home)
    }

    func testAttributionAndEchoes() throws {
        let echo = message("copy") {
            $0.by = "you"; $0.via = "phone"; $0.phone = self.phone; $0.echoOf = "sent"
            $0.origin = GroupOrigin(id: "sent", from: self.phone, at: "09")
        }
        XCTAssertEqual(build([echo], own: ["sent"]), GroupSnapshot(groups: [], dropped: []))
        XCTAssertEqual(try group([echo]).messages.first?.sender, .you)
        let other = message("other") {
            $0.by = "you"; $0.via = "phone"; $0.phone = "ph_other"; $0.echoOf = "sent"
            $0.origin = GroupOrigin(id: "sent", from: "ph_other", at: "09")
        }
        XCTAssertEqual(build([other], own: ["sent"]).groups.first?.messages.first?.sender, .otherPhone)
        let dashboard = message("dashboard") {
            $0.by = "you"; $0.via = "dashboard"; $0.origin = GroupOrigin(id: "dash", from: "dashboard", at: "09")
        }
        XCTAssertEqual(try group([dashboard]).lastLine, "You: dashboard")
        XCTAssertEqual(build([message("forged", from: home) { $0.by = "you" }]).dropped.first?.rule, "G3")
        XCTAssertEqual(build([message("phone", from: phone)]).dropped.first?.rule, "G3")
        XCTAssertEqual(build([message("unknown", from: "ws_unknown")]).dropped.first?.rule, "G3")
        XCTAssertEqual(try group([message("host")]).messages.first?.sender, .host(finance))
        XCTAssertEqual(build([message("origin") {
            $0.by = self.home; $0.origin = GroupOrigin(id: "o", from: self.finance, at: "09")
        }]).dropped.first?.rule, "G4")
        XCTAssertEqual(build([message("nonmember") { $0.by = self.bank }]).dropped.first?.rule, "G4")
    }

    func testNamesUsePairedNamesAndSanitizeUnpairedNames() throws {
        let outsider = "ws_outsider"
        for (supplied, expected) in [("You", "You"), ("Υou", "Υou"), ("You\u{FE0F}", "You"),
                                     ("You\u{3164}", "You"), ("\u{2800}", "Workspace"), ("Yo\u{200B}u", "You"),
                                     ("Ｙou", "You"), ("Other phone", "Other phone"),
                                     ("\u{FFA0}", "Workspace"), ("  ", "Workspace"), ("Guest", "Guest"),
                                     (String(repeating: "a", count: 100), String(repeating: "a", count: 39) + "…")] {
            let m = message("text") {
                $0.by = outsider
                $0.group = GroupInfo(id: "grp_t_fin14a", host: self.finance, title: "Tax",
                    members: [GroupMember(ws: self.finance, name: "Fake host"),
                              GroupMember(ws: self.home, name: "You"), GroupMember(ws: outsider, name: supplied)], seq: 1)
            }
            let g = try group([m])
            XCTAssertEqual(g.names, [finance: "Finance", home: "Home", outsider: expected + " · via Finance"])
            XCTAssertEqual(g.name(of: home), "Home")
            XCTAssertEqual(g.lastLine, "\(expected) · via Finance: text")
            XCTAssertNotEqual(g.name(of: outsider), "You")
            XCTAssertEqual(g.messages.first?.sender, .member(outsider))
            XCTAssertEqual(g.externals, [outsider])
            XCTAssertTrue(g.isExternal(outsider))
            XCTAssertFalse(g.isExternal(home))
            XCTAssertFalse(g.isExternal(finance))
        }
        let paired = message("paired") { $0.by = self.home }
        for (name, expected) in [("", "Workspace"), ("  You ", "You"), (" \n", "Workspace")] {
            let snapshot = GroupStore.build(messages: [paired], workspaces: [finance: "Finance", home: name],
                                            ownPhoneId: phone, ownMessageIds: [])
            XCTAssertEqual(snapshot.groups.first?.lastLine, "\(expected): paired")
            XCTAssertEqual(snapshot.groups.first?.messages.first?.sender, .member(home))
        }
    }

    func testSanitizeNamesAndTitle() throws {
        XCTAssertEqual(GroupStore.sanitize("  Ｆinance  Team  "), "Finance Team")
        XCTAssertEqual(GroupStore.sanitize("A\u{0000}\u{200B}\u{2028}\u{2029}\u{E000}\u{0378}B"), "AB")
        XCTAssertEqual(GroupStore.sanitize("\u{2800}\u{3164}\u{FFA0}\u{FE0F}"), "Workspace")
        XCTAssertEqual(GroupStore.sanitize(String(repeating: "a", count: 40)).count, 40)
        XCTAssertEqual(GroupStore.sanitize(String(repeating: "a", count: 100)).count, 40)
        let m = message("title") {
            $0.group = GroupInfo(id: "grp_t_fin14a", host: self.finance, title: "  Ｔax\u{200B}  ", members: self.members, seq: 1)
        }
        let g = try XCTUnwrap(GroupStore.build(messages: [m], workspaces: [finance: "  Ｆinance\u{FE0F} ", home: "\u{2800}"],
                                             ownPhoneId: phone, ownMessageIds: []).groups.first)
        XCTAssertEqual(g.title, "Tax")
        XCTAssertEqual(g.hostName, "Finance")
        XCTAssertEqual(g.name(of: home), "Workspace")
    }

    func testGroupRequiresMatchingNonNilTicket() {
        for ticket: String? in [nil, "wrong"] {
            let snapshot = build([message("invalid", ticket: ticket)])
            XCTAssertEqual(snapshot.dropped.map(\.rule), ["G1"])
            XCTAssertTrue(snapshot.groups.isEmpty)
        }
        XCTAssertTrue(build([message("valid")]).dropped.isEmpty)
    }

    func testHiddenEchoStillRegistersTaskAndClosure() throws {
        let echo = message("echo") { $0.echoOf = "sent"; $0.phone = self.phone }
        let collision = build([echo, message("collision", host: home)], own: ["sent"])
        XCTAssertTrue(collision.dropped.isEmpty)
        XCTAssertEqual(collision.groups.map(\.key.host), [home])

        let taskEcho = message("task-echo", seq: 2, at: "20") {
            $0.echoOf = "sent"; $0.phone = self.phone
            $0.task = GroupTask(delegate: "d", ws: self.home, status: "done")
        }
        let backwards = message("backwards", seq: 3, at: "30") {
            $0.task = GroupTask(delegate: "d", ws: self.home, status: "working")
        }
        let tasks = build([message("visible", seq: 1), taskEcho, backwards], own: ["sent"])
        XCTAssertEqual(tasks.dropped.map(\.rule), ["G9"])
        XCTAssertEqual(tasks.groups.first?.tasks["d"]?.status, "done")
        XCTAssertEqual(tasks.groups.first?.messages.map(\.id), ["visible"])

        let closeEcho = message("close-echo", seq: 2, at: "20") {
            $0.echoOf = "sent"; $0.phone = self.phone; $0.groupEvent = GroupEvent(kind: "closed")
        }
        let closed = build([message("visible", seq: 1), closeEcho, message("late", seq: 3, at: "30")], own: ["sent"])
        XCTAssertEqual(closed.dropped.map(\.rule), ["closed"])
        XCTAssertEqual(closed.groups.first?.closed, true)
        XCTAssertEqual(closed.groups.first?.messages.map(\.id), ["visible"])
    }

    func testTaskAttributionRequiresMemberToOwnTask() {
        for by in [nil, finance] as [String?] {
            let m = message("host-start") {
                $0.by = by
                $0.task = GroupTask(delegate: "d", ws: self.home, status: "waiting_start")
            }
            XCTAssertTrue(build([m]).dropped.isEmpty)
        }
        let forged = message("forged") {
            $0.by = self.home
            $0.task = GroupTask(delegate: "d", ws: self.finance, status: "working")
        }
        XCTAssertEqual(build([forged]).dropped.map(\.rule), ["G6"])
        let own = message("own") {
            $0.by = self.home
            $0.task = GroupTask(delegate: "d", ws: self.home, status: "working")
        }
        XCTAssertTrue(build([own]).dropped.isEmpty)
    }

    func testDedupeAndUnknownGroup() throws {
        let first = message("first") { $0.origin = GroupOrigin(id: "origin", from: self.finance, at: "09") }
        let duplicate = message("copy", at: "20") { $0.origin = GroupOrigin(id: "origin", from: self.finance, at: "09") }
        let snapshot = build([first, first, duplicate])
        XCTAssertEqual(snapshot.dropped.map(\.rule), ["G7"])
        XCTAssertEqual(snapshot.groups.first?.messages.map(\.id), ["first"])
        XCTAssertEqual(snapshot.groups.first?.startedHere, false)
        XCTAssertEqual(snapshot.groups.first?.hostName, "Finance")
    }

    func testUnknownGroupFromPairedHostIsAccepted() throws {
        let snapshot = build([message("unannounced")])
        XCTAssertTrue(snapshot.dropped.isEmpty)
        let g = try XCTUnwrap(snapshot.groups.first)
        XCTAssertEqual(g.key, GroupKey(host: finance, id: "grp_t_fin14a"))
        XCTAssertEqual(g.messages.map(\.id), ["unannounced"])
        XCTAssertFalse(g.startedHere)
    }

    func testStatefulChecksUseSequenceOrderBeforeDeliveryOrder() throws {
        let done = message("done", seq: 6, at: "10") {
            $0.task = GroupTask(delegate: "d", ws: self.home, status: "done")
        }
        let working = message("working", seq: 5, at: "20") {
            $0.task = GroupTask(delegate: "d", ws: self.home, status: "working")
        }
        let closed = message("closed", seq: 9, at: "30") { $0.groupEvent = GroupEvent(kind: "closed") }
        let text = message("text", seq: 8, at: "40")
        let snapshot = build([done, working, closed, text])
        XCTAssertTrue(snapshot.dropped.isEmpty)
        let g = try XCTUnwrap(snapshot.groups.first)
        XCTAssertEqual(g.messages.map(\.id), ["working", "done", "text", "closed"])
        XCTAssertEqual(g.tasks["d"]?.status, "done")
        XCTAssertTrue(g.closed)
        XCTAssertEqual(g.messages.first?.late, true)
    }

    func testStatefulChecksMergeUnsequencedMessagesByTimeSlot() throws {
        let close = message("closed", seq: 9, at: "30") { $0.groupEvent = GroupEvent(kind: "closed") }
        let earlier = message("earlier", seq: nil, at: "20")
        let later = message("later", seq: nil, at: "40")
        let sequenced = message("seq", seq: 8, at: "10")
        let snapshot = build([sequenced, close, later, earlier])
        XCTAssertEqual(snapshot.groups.first?.messages.map(\.id), ["seq", "earlier", "closed", "later"])
        XCTAssertTrue(snapshot.dropped.isEmpty)
        XCTAssertEqual(snapshot.groups.first?.messages.filter(\.late).map(\.id), ["earlier", "later"])
    }

    func testSequenceOrderTimeInsertionGapsAndNewestMembers() throws {
        let latest = message("s5", seq: 5, at: "30") {
            $0.group = GroupInfo(id: "grp_t_fin14a", host: self.finance, title: "New title",
                                members: self.members + [GroupMember(ws: self.bank, name: "Bank")], seq: 5)
        }
        let g = try group([message("s2", seq: 2, at: "10"), message("before", seq: nil, at: "00"),
                           message("b", seq: nil, at: "20"), message("a", seq: nil, at: "20"), latest,
                           message("s1", seq: 1, at: "40"), message("after", seq: nil, at: "50") { $0.group = latest.message.body.group.map { GroupInfo(id: $0.id, host: $0.host, title: $0.title, members: $0.members) } }])
        XCTAssertEqual(g.messages.map(\.id), ["before", "s1", "s2", "a", "b", "s5", "after"])
        XCTAssertEqual(g.gaps, [3..<5])
        XCTAssertEqual(g.members.last?.ws, bank)
        XCTAssertEqual(g.title, "New title")
        XCTAssertEqual(g.ticketKey, "FIN-14")
        let equalSeq = message("renamed", seq: 5, at: "60") {
            $0.group = GroupInfo(id: "grp_t_fin14a", host: self.finance, title: "Renamed", members: self.members, seq: 5)
        }
        XCTAssertEqual(try group([latest, equalSeq]).title, "New title")
        XCTAssertEqual(try group([message("b", seq: 1, at: "10"), message("a", seq: 1, at: "10")]).messages.map(\.id), ["a", "b"])
    }

    func testEventsQuietAndClosure() throws {
        let start = message("start", seq: 1) { $0.groupEvent = GroupEvent(kind: "created") }
        let close = message("close", seq: 2) { $0.groupEvent = GroupEvent(kind: "closed") }
        let closeAgain = message("closed-again", seq: 3) { $0.groupEvent = GroupEvent(kind: "closed") }
        let snapshot = build([start, close, message("late", seq: 4), closeAgain])
        XCTAssertEqual(snapshot.groups.first?.closed, true)
        XCTAssertEqual(snapshot.groups.first?.startedHere, true)
        XCTAssertEqual(snapshot.groups.first?.messages.map(\.id), ["start", "close", "closed-again"])
        XCTAssertEqual(snapshot.dropped.map(\.rule), ["closed"])
        XCTAssertNil(snapshot.groups.first?.lastLine)
        for kind in ["ack", "working", "note"] {
            XCTAssertEqual(try group([message("quiet") { $0.update = TextUpdate(kind: kind) }]).messages.first?.quiet, true)
        }
        let unknown = try group([message("future") { $0.groupEvent = GroupEvent(kind: "future") }])
        XCTAssertEqual(unknown.messages.first?.event?.kind, "future")
        XCTAssertNil(unknown.lastLine)
        XCTAssertEqual(build([message("bad-event") { $0.groupEvent = GroupEvent(kind: "member_added", ws: self.bank) }]).dropped.first?.rule, "G3")
    }

    func testTaskProgression() throws {
        var timestamp = 0
        func task(_ id: String, _ status: String, by: String? = nil, ws: String? = nil) -> PhoneMessage {
            timestamp += 1
            return message(id, seq: timestamp, at: String(format: "%03d", timestamp)) {
                $0.by = by ?? self.home
                $0.task = GroupTask(delegate: "delegate", ws: ws ?? self.home, status: status)
            }
        }
        let forward = build([task("q", "queued"), task("w", "working"), task("w2", "working")])
        XCTAssertTrue(forward.dropped.isEmpty)
        XCTAssertEqual(forward.groups.first?.tasks["delegate"]?.status, "working")
        let backward = build([task("w", "working"), task("q", "queued")])
        XCTAssertEqual(backward.dropped.map(\.rule), ["G9"])
        for final in ["done", "failed", "denied"] {
            let result = build([task("final", final), task("repeat", final), task("back", "working"),
                                task("different-final", final == "done" ? "failed" : "done")])
            XCTAssertEqual(result.groups.first?.messages.count, 2)
            XCTAssertEqual(result.groups.first?.tasks["delegate"]?.status, final)
            XCTAssertEqual(result.dropped.map(\.rule), ["G9", "G9"])
        }
        XCTAssertEqual(build([task("start", "waiting_start")]).dropped.first?.rule, "G6")
        XCTAssertTrue(build([task("start", "waiting_start", by: finance)]).dropped.isEmpty)
        XCTAssertEqual(build([task("unknown", "unknown")]).dropped.first?.rule, "G9")
        XCTAssertEqual(build([task("nonmember", "working", ws: bank)]).dropped.first?.rule, "G9")
    }

    func testReplyTargetOnlyUsesHostCopiesToPhones() throws {
        let g = try group([message("old", seq: 1), message("new", seq: 2), message("targeted", seq: 3, to: home),
                           message("forged-phone", seq: 4, from: phone)])
        XCTAssertEqual(GroupStore.replyTarget(in: g), "new")
        let closed = try group([message("copy", seq: 1), message("close", seq: 2) { $0.groupEvent = GroupEvent(kind: "closed") }])
        XCTAssertNil(GroupStore.replyTarget(in: closed))
        XCTAssertNil(GroupStore.replyTarget(in: try group([message("targeted", to: home)])))
        // A real phone reply has no group; it stays in the ordinary ticket chat.
        let own = try vector("valid-phone-text-optin-reply")
        XCTAssertEqual(GroupStore.replyTarget(in: try group([message("copy"), own])), "copy")
    }

    func testApprovalRequiresTheOpenMemberQuestionAndEveryCondition() throws {
        let g = try group([message("group") {
            $0.task = GroupTask(delegate: "d", ws: self.bank, ticket: "t_bank", status: "waiting_approval", questionMessage: "q")
            $0.group = GroupInfo(id: "grp_t_fin14a", host: self.finance, title: "Tax",
                                members: self.members + [GroupMember(ws: self.bank, name: "You")], seq: 1)
        }])
        let event = GroupEvent(kind: "approval_needed", ws: bank, delegate: "d", questionMessage: "q")
        func question(id: String = "q", from: String? = nil, options: [String] = ["once", "always", "no"],
                      scope: String? = "Tasks from FINANCE", ticket: String? = "t_bank") -> Question {
            Question(message: QuestionMessage(schema: "orch.msg/1", id: id, from: from ?? bank, to: "phones", type: "question",
                createdAt: "10", ticket: ticket, body: QuestionBody(questionId: "relay:allow", title: nil, text: "Allow?",
                options: options, recommended: nil, scope: scope, allowQuestion: true)), workspaceName: "Bank")
        }
        func card(_ questions: [Question], event e: GroupEvent? = nil) -> ApprovalCard {
            GroupStore.approvalCard(for: e ?? event, in: g, questions: questions)
        }
        XCTAssertEqual(card([question()]), .buttons(question()))
        XCTAssertEqual(GroupStore.approvalCard(for: event, in: g, questions: [question()], late: true), .closed)
        let closed = try group([message("group") {
            $0.group = GroupInfo(id: "grp_t_fin14a", host: self.finance, title: "Tax", members: g.members, seq: 1)
        }, message("closed", seq: 2) {
            $0.group = GroupInfo(id: "grp_t_fin14a", host: self.finance, title: "Tax", members: g.members, seq: 2)
            $0.groupEvent = GroupEvent(kind: "closed")
        }])
        XCTAssertTrue(closed.closed)
        XCTAssertEqual(GroupStore.approvalCard(for: event, in: closed, questions: [question()]), .closed)
        XCTAssertEqual(GroupStore.approvalCard(for: event, in: closed, questions: []), .closed)
        let once = question(options: ["Once", "Always", "No"])
        XCTAssertEqual(card([once]), .answerInWorkspace("Bank"))
        let wire = question(options: ["once", "always", "no"])
        XCTAssertTrue(wire.isAllow)
        XCTAssertEqual(card([wire]), .buttons(wire))
        for q in [question(id: "wrong"), question(from: finance), question(options: ["Always", "No"]),
                  question(options: ["Allow once", "No"]), question(scope: nil), question(scope: "Tasks from Home"),
                  question(scope: "Tasks from Finance Office"), question(scope: "Allow tasks from Finance")] {
            XCTAssertEqual(card([q]), .answerInWorkspace("Bank"))
        }
        XCTAssertEqual(card([question(ticket: "wrong")]), .answerInWorkspace("Bank"))
        XCTAssertEqual(card([question(ticket: nil)]), .answerInWorkspace("Bank"))
        XCTAssertEqual(card([question(scope: "tasks  from Finance")]), .answerInWorkspace("Bank"))
        for task in [
            GroupTask(delegate: "wrong", ws: bank, ticket: "t_bank", status: "waiting_approval", questionMessage: "q"),
            GroupTask(delegate: "", ws: bank, ticket: "t_bank", status: "waiting_approval", questionMessage: "q"),
            GroupTask(delegate: "d", ws: home, ticket: "t_bank", status: "waiting_approval", questionMessage: "q"),
            GroupTask(delegate: "d", ws: "", ticket: "t_bank", status: "waiting_approval", questionMessage: "q"),
            GroupTask(delegate: "d", ws: bank, ticket: "t_bank", status: "waiting_approval"),
            GroupTask(delegate: "d", ws: bank, ticket: "t_bank", status: "waiting_approval", questionMessage: "wrong"),
            GroupTask(delegate: "d", ws: bank, status: "waiting_approval", questionMessage: "q"),
            GroupTask(delegate: "d", ws: bank, ticket: "wrong", status: "waiting_approval", questionMessage: "q")
        ] {
            let altered = PhoneGroup(key: g.key, title: g.title, members: g.members, hostName: g.hostName, names: g.names,
                externals: g.externals, ticketKey: g.ticketKey, ticket: g.ticket, messages: g.messages, closed: false,
                startedHere: g.startedHere, gaps: g.gaps, tasks: ["d": task])
            XCTAssertEqual(GroupStore.approvalCard(for: event, in: altered, questions: [question()]), .answerInWorkspace("Bank"))
        }
        for incomplete in [
            GroupEvent(kind: "approval_needed", ws: bank, delegate: "d"),
            GroupEvent(kind: "approval_needed", ws: bank, questionMessage: "q"),
            GroupEvent(kind: "approval_needed", delegate: "d", questionMessage: "q")
        ] {
            XCTAssertEqual(card([question()], event: incomplete), .answerInWorkspace(g.name(of: incomplete.ws ?? "")))
        }

        XCTAssertEqual(card([question()], event: GroupEvent(kind: "approval_needed", ws: bank, delegate: "wrong", questionMessage: "q")), .answerInWorkspace("Bank"))
        XCTAssertEqual(card([question(id: "other")], event: GroupEvent(kind: "approval_needed", ws: bank, delegate: "d", questionMessage: "other")), .answerInWorkspace("Bank"))
        XCTAssertEqual(card([question(from: home)], event: GroupEvent(kind: "approval_needed", ws: home, delegate: "d", questionMessage: "q")), .answerInWorkspace("Home"))
        let trimmed = question(scope: "  tasks FROM Finance \n")
        XCTAssertEqual(card([trimmed]), .buttons(trimmed))
        XCTAssertEqual(card([question()], event: GroupEvent(kind: "created", ws: bank, questionMessage: "q")),
                       .answerInWorkspace("Bank"))
        let outsider = "ws_outsider"
        XCTAssertEqual(card([question(from: outsider)], event: GroupEvent(kind: "approval_needed", ws: outsider, questionMessage: "q")),
                       .answerInWorkspace("Workspace"))
        XCTAssertEqual(card([]), .answerInWorkspace("Bank"))
        XCTAssertEqual(card([question()], event: GroupEvent(kind: "approval_needed", ws: bank)), .answerInWorkspace("Bank"))
        XCTAssertEqual(card([question()], event: GroupEvent(kind: "approval_needed", questionMessage: "q")), .answerInWorkspace("Workspace"))
    }

    func testLimitsAndSharedFiles() throws {
        for list in [members + [members[0]], [GroupMember(ws: home, name: "Home")]] {
            let m = message("members") { $0.group = GroupInfo(id: "grp_t_fin14a", host: self.finance, title: "Tax", members: list) }
            XCTAssertEqual(build([m]).dropped.first?.rule, "limit")
        }
        for title in ["", String(repeating: "a", count: 121)] {
            let m = message("title") { $0.group = GroupInfo(id: "grp_t_fin14a", host: self.finance, title: title, members: self.members) }
            XCTAssertEqual(build([m]).dropped.first?.rule, "limit")
        }
        XCTAssertEqual(build([message("missing") { $0.sharedFiles = ["b_missing"] }]).dropped.first?.rule, "G5")
        let file = message("file") {
            $0.sharedFiles = ["b_file"]
            $0.ticketView = TicketSnapshot(attachments: [TicketSnapshot.Attachment(blobId: "b_file", artifactId: "a_artifact")])
        }
        XCTAssertTrue(build([file]).dropped.isEmpty, "G5 matches blob ids, not UI artifact identity")
    }

    func testNewFieldsAreOptionalAndDecodeTolerantly() throws {
        let old = try JSONCoding.decoder.decode(TextBody.self, from: Data(#"{"text":"old"}"#.utf8))
        XCTAssertEqual(old, TextBody(text: "old"))
        let malformed = try JSONCoding.decoder.decode(TextBody.self, from: Data(#"{"text":"ok","group":42,"by":true,"task":[],"shared_files":false}"#.utf8))
        XCTAssertEqual(malformed, TextBody(text: "ok"))
        let body = TextBody(text: "outgoing", group: GroupInfo(id: "grp_t_fin14a", host: finance, title: "Tax", members: members),
                            by: "you", echoOf: "sent")
        let roundTrip = try JSONCoding.decoder.decode(TextBody.self, from: JSONCoding.encoder.encode(body))
        XCTAssertEqual(roundTrip, TextBody(text: "outgoing"), "The phone never encodes group fields")
    }
    private func vectorObject(_ name: String) throws -> [String: Any] {
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        return try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: root.appendingPathComponent("contracts/vectors/chat-groups/\(name).json"))) as? [String: Any])
    }

    func testFutureHostClockDoesNotFlushAnotherGroupsGap() throws {
        let start = message("start", seq: 1, at: "0", host: home)
        let buffered = message("buffered", seq: 3, at: "1", host: home)
        let future = message("future", seq: 1, at: "2999-01-01T00:00:00Z")
        let close = message("close", seq: 2, at: "2", host: home) {
            $0.groupEvent = GroupEvent(kind: "closed")
        }
        // Only this group’s receive clock can flush its gap before the close arrives.
        let snapshot = GroupStore.build(messages: [start, buffered, future, close].reversed(),
            workspaces: workspaces, ownPhoneId: phone, ownMessageIds: [], receivedAt: ["start": Date(timeIntervalSince1970: 0),
                "buffered": Date(timeIntervalSince1970: 1), "future": Date(timeIntervalSince1970: 2),
                "close": Date(timeIntervalSince1970: 3)], now: Date(timeIntervalSince1970: 1000))
        let g = try XCTUnwrap(snapshot.groups.first { $0.key.host == home })
        XCTAssertTrue(g.closed)
        XCTAssertEqual(g.gaps, [])
        XCTAssertEqual(g.messages.map(\.id), ["start", "close"])
        XCTAssertFalse(try XCTUnwrap(g.messages.last).late)
        XCTAssertEqual(snapshot.dropped.map(\.messageId), ["buffered"])
        XCTAssertEqual(snapshot.dropped.map(\.rule), ["closed"])
    }

    func testCreatedAtIsDisplayOnlyAndMissingReceiveTimesUseNow() throws {
        let now = Date(timeIntervalSince1970: 1000)
        let start = message("start", seq: 1, at: "0")
        let future = message("future", seq: 3, at: "2999-01-01T00:00:00Z")
        let snapshot = GroupStore.build(messages: [future, start], workspaces: workspaces,
            ownPhoneId: phone, ownMessageIds: [], now: now)
        let g = try XCTUnwrap(snapshot.groups.first)
        XCTAssertEqual(g.messages.map(\.id), ["start"])
        XCTAssertEqual(g.appliedSeq, 1)
        XCTAssertEqual(g.gaps, [])
        // A future creation and a creation at now must share the same rate window.
        let creations = (0..<6).map { n in
            message("new\(n)", seq: 1, at: n < 5 ? "2999-01-01T00:00:00Z" : "1000", ticket: "t_\(n)") {
                $0.group = GroupInfo(id: "grp_t_\(n)", host: self.finance, title: "Group", members: self.members, seq: 1)
            }
        }
        let capped = GroupStore.build(messages: creations.reversed(), workspaces: workspaces,
            ownPhoneId: phone, ownMessageIds: [], now: now)
        XCTAssertEqual(capped.groups.count, 5)
        XCTAssertEqual(capped.dropped.map(\.messageId), ["new5"])
        XCTAssertEqual(capped.dropped.map(\.rule), ["cap"])
        for at in ["garbage", "", "NaN", "inf"] {
            let bad = build([message("bad", seq: 1, at: at)])
            XCTAssertEqual(bad.groups.first?.messages.map(\.id), ["bad"])
            XCTAssertTrue(bad.dropped.isEmpty)
        }
    }

    func testSeqlessMessagesAreShownWithoutChangingStateOrLatest() throws {
        let start = message("start", seq: 1)
        let close = message("close", at: "20") {
            $0.groupEvent = GroupEvent(kind: "closed")
            $0.group = GroupInfo(id: "grp_t_fin14a", host: self.finance, title: "Wrong", members: [self.members[0]])
        }
        let task = message("task", seq: nil, at: "30") {
            $0.task = GroupTask(delegate: "d", ws: self.home, status: "done")
        }
        let g = try group([start, close, task])
        XCTAssertEqual(g.messages.map(\.id), ["start", "close", "task"])
        XCTAssertEqual(g.messages.filter(\.late).map(\.id), ["close", "task"])
        XCTAssertFalse(g.closed)
        XCTAssertTrue(g.tasks.isEmpty)
        XCTAssertEqual(g.title, "Tax")
        XCTAssertEqual(g.members, members)
        XCTAssertEqual(g.appliedSeq, 1)
        let unknown = build([close])
        XCTAssertTrue(unknown.groups.isEmpty)
        XCTAssertEqual(unknown.dropped, [GroupDrop(messageId: "close", rule: "G12", reason: "group message without seq")])
    }

    func testPhoneIgnoresMemberFromSeqForInitialAppliedSequence() throws {
        let added = message("added", seq: 5) {
            $0.groupEvent = GroupEvent(kind: "member_added", ws: self.home, name: "Home", fromSeq: Int(Int32.max))
        }
        let task = message("task", seq: 6) {
            $0.task = GroupTask(delegate: "d", ws: self.home, status: "working")
        }
        let g = try group([added, task])
        XCTAssertEqual(g.appliedSeq, 6)
        XCTAssertEqual(g.gaps, [])
        XCTAssertTrue(g.messages.allSatisfy { !$0.late })
        XCTAssertEqual(g.tasks["d"]?.status, "working")
    }

    func testOutOfRangeSequencesAreDropped() {
        for seq in [Int.max, Int.min, 0, -5, Int(Int32.max) + 1] {
            for m in [message("bad-seq", seq: seq), message("bad-from-seq", seq: 1, edit: {
                $0.groupEvent = GroupEvent(kind: "member_added", ws: self.home, name: "Home", fromSeq: seq)
            })] {
                let expected = GroupDrop(messageId: m.id, rule: "G12", reason: "seq out of range")
                XCTAssertEqual(GroupStore.accept(m, workspaces: workspaces), expected)
                let snapshot = build([m])
                XCTAssertEqual(snapshot.dropped, [expected])
                XCTAssertTrue(snapshot.groups.isEmpty)
            }
        }
        XCTAssertNil(GroupStore.accept(message("maximum", seq: Int(Int32.max)), workspaces: workspaces))
    }

    func testLargeJumpSkipsImmediatelyWithBoundedGapStorage() throws {
        let now = Date(timeIntervalSince1970: 10)
        var order = GroupOrder(appliedSeq: 5)
        XCTAssertEqual(order.receive(seq: 1_000_000, receivedAt: now, now: now), .skipJumpAndApply)
        XCTAssertEqual(order.appliedSeq, 1_000_000)
        XCTAssertEqual(order.released, [1_000_000])
        XCTAssertTrue(order.buffered.isEmpty)
        XCTAssertEqual(order.gaps, [6..<1_000_000])
        XCTAssertLessThanOrEqual(order.gaps.count, 1)
        let snapshot = GroupStore.build(messages: [message("jump", seq: 1_000_000), message("start", seq: 5)],
                                        workspaces: workspaces, ownPhoneId: phone, ownMessageIds: [], now: now)
        let g = try XCTUnwrap(snapshot.groups.first)
        XCTAssertEqual(g.appliedSeq, 1_000_000)
        XCTAssertEqual(g.gaps, [6..<1_000_000])
        XCTAssertLessThanOrEqual(g.gaps.count, 1)
        XCTAssertTrue(g.hasGaps)
        XCTAssertTrue(snapshot.dropped.isEmpty)
    }

    func testJumpBoundarySupersedesBufferedMessages() {
        let now = Date(timeIntervalSince1970: 10)
        var order = GroupOrder(appliedSeq: 5)
        XCTAssertEqual(order.receive(seq: 1005, receivedAt: now, now: now), .buffer)
        XCTAssertEqual(order.receive(seq: 1006, receivedAt: now, now: now), .skipJumpAndApply)
        XCTAssertEqual(order.released, [1006])
        XCTAssertEqual(order.superseded, [1005])
        XCTAssertEqual(order.gaps, [6..<1006])
        XCTAssertEqual(order.appliedSeq, 1006)
        XCTAssertTrue(order.buffered.isEmpty)
    }

    func testDirectOrderExtremeIntegersAndRangeCap() {
        let now = Date(timeIntervalSince1970: 10)
        for initial: Int? in [nil, Int.min, Int.max, 5] {
            var order = GroupOrder(appliedSeq: initial, fromSeq: Int.min)
            for seq in [Int.max, Int.min, 0, -5, Int(Int32.max) + 1] {
                XCTAssertEqual(order.receive(seq: seq, receivedAt: now, now: now), .lateShowNoState)
                XCTAssertTrue(order.buffered.isEmpty)
                XCTAssertTrue(order.gaps.isEmpty)
                XCTAssertTrue(order.released.isEmpty)
            }
            _ = order.receive(seq: 1, receivedAt: now, now: now)
            order.flush(now: now)
            XCTAssertLessThanOrEqual(order.gaps.count, 1)
            XCTAssertTrue(order.buffered.isEmpty)
        }
        var extreme = GroupOrder(appliedSeq: Int.max, buffered: [Int.max: now])
        extreme.flush(now: now.addingTimeInterval(600))
        XCTAssertTrue(extreme.buffered.isEmpty)
        XCTAssertEqual(extreme.appliedSeq, Int.max)

        var order = GroupOrder(appliedSeq: 1)
        for seq in stride(from: 2000, through: 120_000, by: 2000) {
            XCTAssertEqual(order.receive(seq: seq, receivedAt: now, now: now), .skipJumpAndApply)
            XCTAssertLessThanOrEqual(order.gaps.count, 50)
            XCTAssertTrue(order.buffered.isEmpty)
        }
        XCTAssertEqual(order.gaps.count, 50)
        XCTAssertEqual(order.gaps.first, 20_001..<22_000)
        XCTAssertEqual(order.gaps.last, 118_001..<120_000)
    }

    func testBufferSkipsOnlyOnThe51stWaitingMessage() {
        let now = Date(timeIntervalSince1970: 10)
        var order = GroupOrder(appliedSeq: 1)
        for seq in 3...51 {
            XCTAssertEqual(order.receive(seq: seq, receivedAt: now, now: now), .buffer)
        }
        XCTAssertEqual(order.buffered.count, 49)
        XCTAssertEqual(order.receive(seq: 52, receivedAt: now, now: now), .buffer)
        XCTAssertEqual(order.buffered.count, 50)
        XCTAssertEqual(order.appliedSeq, 1)
        XCTAssertTrue(order.gaps.isEmpty)
        XCTAssertEqual(order.receive(seq: 53, receivedAt: now, now: now), .skipGapAndApply)
        XCTAssertEqual(order.appliedSeq, 53)
        XCTAssertEqual(order.gaps, [2..<3])
        XCTAssertTrue(order.buffered.isEmpty)
    }

    func testHistoryCapKeepsNewest50ClosedGroupsAndAllOpenGroups() {
        for tiedDates in [false, true] {
            var times: [String: Date] = [:]
            let input = (0..<62).map { index in
                let id = "history-\(index)"
                times[id] = Date(timeIntervalSince1970: Double(index * 3601))
                return message(id, at: tiedDates ? "same" : String(format: "%03d", index), ticket: "t_\(index)") {
                    $0.group = GroupInfo(id: "grp_t_\(index)", host: self.finance, title: "History", members: self.members, seq: 1)
                    // Oldest and newest open groups both survive.
                    if index > 0 && index < 61 { $0.groupEvent = GroupEvent(kind: "closed") }
                }
            }
            let snapshot = build(input, receivedAt: times)
            XCTAssertTrue(snapshot.dropped.isEmpty)
            XCTAssertEqual(snapshot.groups.filter(\.closed).count, 50)
            XCTAssertEqual(Set(snapshot.groups.filter(\.closed).map(\.key.id)), Set((11...60).map { "grp_t_\($0)" }))
            XCTAssertEqual(Set(snapshot.groups.filter { !$0.closed }.map(\.key.id)), ["grp_t_0", "grp_t_61"])
        }
    }

    func testHistoryCapIgnoresSpoofedAndPostCloseMessages() {
        var times: [String: Date] = [:]
        var arrival: [String: Int] = [:]
        let input = (0..<52).map { index in
            let id = "history-\(index)"
            times[id] = Date(timeIntervalSince1970: Double(index * 3601))
            arrival[id] = index
            return message(id, at: index == 0 ? "zzz" : "9999-01-01", ticket: "t_\(index)") {
                $0.group = GroupInfo(id: "grp_t_\(index)", host: self.finance, title: "History", members: self.members, seq: 1)
                $0.groupEvent = GroupEvent(kind: "closed")
            }
        }
        let expected = Set((2..<52).map { "grp_t_\($0)" })
        let spoof = message("spoof", from: home, ticket: "t_1") {
            $0.group = GroupInfo(id: "grp_t_1", host: self.finance, title: "History", members: self.members, seq: 2)
        }
        let postClose = message("post-close", seq: nil, ticket: "t_1") {
            $0.group = GroupInfo(id: "grp_t_1", host: self.finance, title: "History", members: self.members)
        }
        let repeatedClose = message("repeated-close", ticket: "t_1") {
            $0.group = GroupInfo(id: "grp_t_1", host: self.finance, title: "History", members: self.members, seq: 2)
            $0.groupEvent = GroupEvent(kind: "closed")
        }
        for extra in [spoof, postClose, repeatedClose] {
            arrival[extra.id] = 1000
            times[extra.id] = Date(timeIntervalSince1970: 52 * 3601)
            for explicitArrival in [false, true] {
                let snapshot = build(input + [extra], receivedAt: times, arrival: explicitArrival ? arrival : [:])
                XCTAssertEqual(Set(snapshot.groups.map(\.key.id)), expected, extra.id)
                if extra.id == spoof.id { XCTAssertTrue(snapshot.dropped.contains { $0.messageId == spoof.id }) }
            }
        }
        // A known arrival outranks every missing arrival, regardless of input position.
        let partial = build(input, receivedAt: times, arrival: ["history-0": 0])
        XCTAssertEqual(Set(partial.groups.map(\.key.id)), Set(([0] + Array(3..<52)).map { "grp_t_\($0)" }))
    }

    func testOrderVectors() throws {
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        let files = try FileManager.default.contentsOfDirectory(atPath: root.appendingPathComponent("contracts/vectors/chat-groups").path)
        for file in files where file.hasPrefix("valid-seq-") {
            let name = String(file.dropLast(5)), object = try vectorObject(name)
            let context = try XCTUnwrap((object["context"] as? [String: Any])?["order"] as? [String: Any])
            let expect = try XCTUnwrap(object["expect"] as? [String: Any])
            let m = try vector(name)
            let now = Date(timeIntervalSince1970: context["now_s"] as? Double ?? 1000)
            let firstReceive = Date(timeIntervalSince1970: context["first_buffered_recv_s"] as? Double ?? now.timeIntervalSince1970)
            let buffered = Dictionary(uniqueKeysWithValues: (context["buffered"] as? [Int] ?? []).map { ($0, firstReceive) })
            var order = GroupOrder(appliedSeq: context["applied_seq"] as? Int, fromSeq: context["from_seq"] as? Int, buffered: buffered)
            let outcome = order.receive(seq: try XCTUnwrap(m.message.body.group?.seq), receivedAt: now, now: now)
            XCTAssertEqual(outcome.rawValue, expect["order"] as? String, name)
            XCTAssertEqual(order.appliedSeq, expect["applied_after"] as? Int, name)
        }
    }

    func testFinalContractVectorsInStore() throws {
        let now = Date(timeIntervalSince1970: 1005)
        for name in ["invalid-seq-zero", "invalid-seq-over-int31"] {
            let snapshot = build([try vector(name)], now: now)
            XCTAssertTrue(snapshot.groups.isEmpty, name)
            XCTAssertEqual(snapshot.dropped.map(\.rule), ["G12"], name)
        }
        let seqless = try vector("invalid-groupwide-without-seq")
        let shown = try XCTUnwrap(build([message("start", seq: 6), seqless]).groups.first)
        XCTAssertEqual(shown.appliedSeq, 6)
        XCTAssertEqual(shown.title, "Tax")
        XCTAssertEqual(shown.members, members)
        XCTAssertTrue(try XCTUnwrap(shown.messages.first { $0.id == seqless.id }).late)

        for name in ["valid-seq-jump-1000-buffers", "valid-seq-jump-1001-skips",
                     "valid-seq-created-at-future-does-not-flush"] {
            let m = try vector(name)
            let start = message("start", seq: 6)
            let pending = message("pending", seq: 8) {
                $0.groupEvent = GroupEvent(kind: "closed")
            }
            let otherStart = message("other-start", seq: 1, host: home)
            let otherGap = message("other-gap", seq: 3, host: home)
            let input = [start, pending, otherStart, otherGap, m]
            let times = Dictionary(uniqueKeysWithValues: input.map { ($0.id, Date(timeIntervalSince1970: 1000)) })
            let snapshot = build(input, receivedAt: times, now: now)
            let g = try XCTUnwrap(snapshot.groups.first { $0.key.host == finance })
            let skips = name == "valid-seq-jump-1001-skips"
            XCTAssertEqual(g.appliedSeq, skips ? 1007 : 6, name)
            XCTAssertEqual(g.gaps, skips ? [7..<1007] : [], name)
            XCTAssertEqual(Set(g.messages.map(\.id)), skips ? Set(["start", "pending", m.id]) : Set(["start"]), name)
            XCTAssertFalse(g.closed, name)
            if skips { XCTAssertTrue(try XCTUnwrap(g.messages.first { $0.id == "pending" }).late) }
            let other = try XCTUnwrap(snapshot.groups.first { $0.key.host == home })
            XCTAssertEqual(other.appliedSeq, 1, name)
            XCTAssertEqual(other.messages.map(\.id), ["other-start"], name)
            XCTAssertTrue(snapshot.dropped.isEmpty, name)
        }
    }

    func testReceiveOrderOverridesCreatedAtAndInputOrder() throws {
        let start = message("start", seq: 1, at: "2099-01-01T00:00:00Z")
        let close = message("close", seq: 2, at: "garbage") { $0.groupEvent = GroupEvent(kind: "closed") }
        let times = ["start": Date(timeIntervalSince1970: 10), "close": Date(timeIntervalSince1970: 11)]
        for input in [[start, close], [close, start]] {
            let snapshot = build(input, receivedAt: times, arrival: ["start": 0, "close": 1], now: Date(timeIntervalSince1970: 12))
            let g = try XCTUnwrap(snapshot.groups.first)
            XCTAssertEqual(g.messages.map(\.id), ["start", "close"])
            XCTAssertTrue(g.closed)
            XCTAssertTrue(g.messages.allSatisfy { !$0.late })
            XCTAssertTrue(snapshot.dropped.isEmpty)
        }
    }

    func testArrivalOrderAcrossGroupsIgnoresHostDatesAndReceiveTimeTies() throws {
        let first = message("first", seq: 2, at: "2099", host: home)
        let second = message("second", seq: 1, at: "2000")
        let backdated = message("backdated", seq: 900, at: "1900", host: home)
        // This is the host-date-sorted display array, not relay arrival order.
        let snapshot = GroupStore.build(messages: [first, second, backdated], workspaces: workspaces,
            ownPhoneId: phone, ownMessageIds: [], arrival: ["first": 0, "second": 1, "backdated": 2],
            now: Date(timeIntervalSince1970: 10))
        XCTAssertEqual(snapshot.groups.map(\.key.host), [home, finance])
        let g = try XCTUnwrap(snapshot.groups.first)
        XCTAssertEqual(g.appliedSeq, 2)
        XCTAssertEqual(g.messages.map(\.id), ["first"])
        XCTAssertTrue(g.gaps.isEmpty)
        XCTAssertTrue(snapshot.dropped.isEmpty)
    }

    func testUnknownSeqlessMessagesDoNotCreateGroupsOrConsumeCaps() {
        let unknown = (0..<6).map { index in
            message("unknown-\(index)", seq: nil, ticket: "t_\(index)") {
                $0.group = GroupInfo(id: "grp_t_\(index)", host: self.finance, title: "Unknown", members: self.members)
            }
        }
        let valid = (0..<5).map { index in
            message("unknown-\(index)", seq: 1, ticket: "t_\(index)") {
                $0.group = GroupInfo(id: "grp_t_\(index)", host: self.finance, title: "Valid", members: self.members, seq: 1)
            }
        }
        XCTAssertTrue(build(unknown).groups.isEmpty)
        let snapshot = build(unknown + valid)
        XCTAssertEqual(snapshot.dropped, unknown.map {
            GroupDrop(messageId: $0.id, rule: "G12", reason: "group message without seq")
        })
        XCTAssertEqual(snapshot.groups.count, 5)
        XCTAssertTrue(snapshot.groups.allSatisfy { $0.title == "Valid" && $0.appliedSeq == 1 })
    }

    func testKnownSeqlessMessagesDoNotReserveIdsOrOriginsOrChangeState() throws {
        let unsequenced = message("reused", seq: nil) {
            $0.origin = GroupOrigin(id: "origin", from: self.finance, at: "0")
            $0.groupEvent = GroupEvent(kind: "closed")
            $0.task = GroupTask(delegate: "d", ws: self.home, status: "done")
            $0.group = GroupInfo(id: "grp_t_fin14a", host: self.finance, title: "Ignored", members: self.members)
        }
        let sameId = message("reused", seq: 2)
        let sameOrigin = message("origin-copy", seq: 3) { $0.origin = unsequenced.message.body.origin }
        let snapshot = build([message("start"), unsequenced, unsequenced, sameId, sameOrigin])
        let g = try XCTUnwrap(snapshot.groups.first)
        XCTAssertTrue(snapshot.dropped.isEmpty)
        XCTAssertEqual(g.messages.count, 5)
        XCTAssertEqual(g.messages.filter(\.late).count, 2)
        XCTAssertEqual(g.appliedSeq, 3)
        XCTAssertEqual(g.title, "Tax")
        XCTAssertFalse(g.closed)
        XCTAssertTrue(g.tasks.isEmpty)
    }

    func testSeqlessAndOldMessagesDoNotAdvanceClockOrFlush() throws {
        for seq: Int? in [nil, 1] {
            let input = [message("start", seq: 1), message("pending", seq: 3),
                         message("late", seq: seq), message("next", seq: 4), message("fill", seq: 2)]
            let times = ["start": 0.0, "pending": 1, "late": 10000, "next": 2, "fill": 3]
                .mapValues { Date(timeIntervalSince1970: $0) }
            let snapshot = build(input, receivedAt: times, now: Date(timeIntervalSince1970: 4))
            let g = try XCTUnwrap(snapshot.groups.first)
            XCTAssertTrue(snapshot.dropped.isEmpty)
            XCTAssertEqual(g.appliedSeq, 4)
            XCTAssertTrue(g.gaps.isEmpty)
            XCTAssertEqual(g.messages.filter(\.late).map(\.id), ["late"])
            XCTAssertEqual(Set(g.messages.map(\.id)), Set(input.map(\.id)))
        }
    }

    func testRateVectorsUseReceiveTimesInStore() throws {
        for name in ["valid-created-under-cap", "valid-implicit-group-under-cap",
                     "invalid-created-over-rate", "invalid-implicit-group-over-rate"] {
            let context = try XCTUnwrap(try vectorObject(name)["context"] as? [String: Any])
            let seconds = try XCTUnwrap(context["creations_recv_s"] as? [Double])
            let now = Date(timeIntervalSince1970: try XCTUnwrap(context["now_s"] as? Double))
            var times: [String: Date] = [:]
            var input = seconds.enumerated().map { index, seconds in
                let m = message("prior-\(index)", seq: 1, at: "2099-01-01T00:00:00Z", ticket: "t_prior\(index)") {
                    $0.group = GroupInfo(id: "grp_t_prior\(index)", host: self.finance, title: "Prior", members: self.members, seq: 1)
                }
                times[m.id] = Date(timeIntervalSince1970: seconds)
                return m
            }
            let candidate = try vector(name)
            times[candidate.id] = now
            input.append(candidate)
            let snapshot = build(input, receivedAt: times, now: now)
            XCTAssertEqual(snapshot.dropped.map(\.messageId), name.hasPrefix("invalid") ? [candidate.id] : [], name)
            XCTAssertEqual(snapshot.dropped.map(\.rule), name.hasPrefix("invalid") ? ["cap"] : [], name)
        }
    }

    func testBufferDrainTimeoutAndLateState() throws {
        let start = message("start", seq: 1, at: "0")
        let done = message("done", seq: 3, at: "1") { $0.task = GroupTask(delegate: "d", ws: self.home, status: "done") }
        func snapshot(_ input: [PhoneMessage], now: Double) -> GroupSnapshot {
            let seconds: [String: Double] = ["start": 0, "done": 1, "tick": 601, "working": 602, "close": 603, "second": 2]
            return GroupStore.build(messages: input.reversed(), workspaces: workspaces, ownPhoneId: phone, ownMessageIds: [],
                receivedAt: seconds.mapValues { Date(timeIntervalSince1970: $0) }, now: Date(timeIntervalSince1970: now))
        }
        let buffered = snapshot([start, done], now: 600)
        XCTAssertEqual(buffered.groups.first?.messages.map(\.id), ["start"])
        XCTAssertEqual(buffered.groups.first?.appliedSeq, 1)
        let expired = snapshot([start, done], now: 601)
        XCTAssertEqual(expired.groups.first?.tasks["d"]?.status, "done")
        XCTAssertEqual(expired.groups.first?.gaps, [2..<3])
        let working = message("working", seq: 2, at: "602") {
            $0.task = GroupTask(delegate: "d", ws: self.home, status: "working")
        }
        // Advance the group's clock before the late message arrives.
        let tick = message("tick", seq: 4, at: "601")
        let lateClose = message("close", seq: 2, at: "603") {
            $0.groupEvent = GroupEvent(kind: "closed")
            $0.group = GroupInfo(id: "grp_t_fin14a", host: self.finance, title: "Late", members: [self.members[0]], seq: 2)
        }
        let late = snapshot([start, done, tick, working, lateClose], now: 603)
        let g = try XCTUnwrap(late.groups.first)
        XCTAssertTrue(late.dropped.isEmpty)
        XCTAssertEqual(g.tasks["d"]?.status, "done")
        XCTAssertFalse(g.closed)
        XCTAssertEqual(g.members, members)
        XCTAssertEqual(g.gaps, [2..<3])
        XCTAssertEqual(g.messages.filter(\.late).map(\.id), ["close", "working"])
        let filled = snapshot([start, done, message("second", seq: 2, at: "2")], now: 3)
        XCTAssertEqual(filled.groups.first?.messages.map(\.id), ["start", "second", "done"])
        XCTAssertEqual(filled.groups.first?.appliedSeq, 3)
        XCTAssertEqual(filled.groups.first?.gaps, [])
        var order = GroupOrder(appliedSeq: 1, buffered: [3: Date(timeIntervalSince1970: 0), 5: Date(timeIntervalSince1970: 0)])
        order.flush(now: Date(timeIntervalSince1970: 600))
        XCTAssertEqual(order.released, [3, 5])
        XCTAssertEqual(order.gaps, [2..<3, 4..<5])
    }

    func testAttributionAndKeyVectors() throws {
        for (name, sender) in [("valid-unknown-phone-shown-other-phone", GroupSender.otherPhone),
                               ("valid-own-phone-shown-you", .you),
                               ("invalid-origin-phone-not-paired-to-host", .otherPhone)] {
            let object = try vectorObject(name), m = try vector(name)
            let own = ((object["context"] as? [String: Any])?["own_phones"] as? [String])?.first ?? phone
            // Host pairing is a host-side check: the phone cannot verify it and accepts Other phone.
            let snapshot = GroupStore.build(messages: [m], workspaces: workspaces, ownPhoneId: own, ownMessageIds: [])
            XCTAssertTrue(snapshot.dropped.isEmpty, name)
            XCTAssertEqual(snapshot.groups.first?.messages.first?.sender, sender, name)
        }
        let forged = try vector("invalid-nonhost-message-at-member-known-group", to: "phones")
        XCTAssertEqual(build([message("known"), forged]).dropped.last?.rule, "G3")
        let otherHost = try vector("valid-same-id-other-host-is-a-separate-group", to: "phones")
        var paired = workspaces
        paired[otherHost.message.from] = "Other host"
        let separate = GroupStore.build(messages: [otherHost, message("known")], workspaces: paired, ownPhoneId: phone, ownMessageIds: [])
        XCTAssertEqual(separate.groups.count, 2)
        let append = try vector("valid-known-group-same-key-appends", to: "phones")
        XCTAssertEqual(build([message("known"), append]).groups.first?.messages.count, 2)
        let duplicate = try vector("invalid-duplicate-origin-same-group-key", to: "phones")
        let prior = message("prior") { $0.origin = duplicate.message.body.origin }
        XCTAssertEqual(build([prior, duplicate]).dropped.last?.rule, "G7")
    }

    func testCapVectorsAndSlidingHour() throws {
        for name in ["valid-created-under-cap", "invalid-created-over-group-cap", "invalid-created-over-rate",
                     "valid-implicit-group-under-cap", "invalid-implicit-group-over-cap", "invalid-implicit-group-over-rate"] {
            let object = try vectorObject(name), context = try XCTUnwrap(object["context"] as? [String: Any])
            XCTAssertEqual(GroupCaps.accepts(openGroups: try XCTUnwrap(context["open_groups_of_host"] as? Int),
                                            createdLastHour: (context["creations_recv_s"] as? [Double] ?? []).filter {
                                                $0 > (context["now_s"] as? Double ?? 0) - 3600 && $0 <= (context["now_s"] as? Double ?? 0)
                                            }.count), name.hasPrefix("valid-"), name)
        }
        var receiveTimes: [String: Date] = [:]
        func creation(_ n: Int, at: Int, host: String? = nil, close: Bool = false) -> PhoneMessage {
            receiveTimes["new\(n)"] = Date(timeIntervalSince1970: Double(at))
            return message("new\(n)", at: "untrusted display date", host: host, ticket: "t_\(n)") {
                $0.group = GroupInfo(id: "grp_t_\(n)", host: host ?? self.finance, title: "Group", members: self.members, seq: 1)
                if close { $0.groupEvent = GroupEvent(kind: "closed") }
            }
        }
        func receivedBuild(_ messages: [PhoneMessage]) -> GroupSnapshot {
            build(messages, receivedAt: receiveTimes, now: receiveTimes.values.max() ?? Date())
        }
        let firstFive = (0..<5).map { creation($0, at: $0) }
        XCTAssertEqual(receivedBuild(firstFive + [creation(5, at: 5)]).dropped.map(\.rule), ["cap"])
        XCTAssertTrue(receivedBuild(firstFive + [creation(5, at: 3600)]).dropped.isEmpty)
        XCTAssertTrue(receivedBuild(firstFive + [creation(5, at: 5, host: home)]).dropped.isEmpty)
        let twenty = (0..<20).map { creation($0, at: $0 * 3600) }
        XCTAssertEqual(receivedBuild(twenty + [creation(20, at: 72000)]).dropped.map(\.rule), ["cap"])
        XCTAssertTrue(receivedBuild(twenty.dropLast() + [creation(19, at: 68400, close: true), creation(20, at: 72000)]).dropped.isEmpty)
        let retained = (0..<101).map { creation($0, at: $0 * 3601, close: true) }
        let snapshot = receivedBuild(retained)
        XCTAssertEqual(snapshot.groups.count, 50)
        XCTAssertTrue(snapshot.groups.allSatisfy(\.closed))
        XCTAssertTrue(snapshot.dropped.isEmpty)
    }

    func testAllowVectorsAndMapping() throws {
        var g = try group([vector("valid-member-added-from-seq")])
        for name in ["valid-allow-question-wire-options", "valid-allow-question-old-wording-answer-in-bank", "invalid-allow-question-ui-words-on-wire"] {
            let object = try vectorObject(name)
            let q = Question(message: try JSONCoding.decoder.decode(QuestionMessage.self, from: JSONSerialization.data(withJSONObject: try XCTUnwrap(object["message"]))), workspaceName: "Bank")
            g = PhoneGroup(key: g.key, title: g.title, members: g.members, hostName: g.hostName, names: g.names,
                externals: g.externals, ticketKey: g.ticketKey, ticket: g.ticket, messages: g.messages, closed: false,
                startedHere: g.startedHere, gaps: g.gaps,
                tasks: ["d": GroupTask(delegate: "d", ws: bank, ticket: q.message.ticket, status: "waiting_approval", questionMessage: q.id)])
            let event = GroupEvent(kind: "approval_needed", ws: bank, delegate: "d", questionMessage: q.id)
            let isWire = name == "valid-allow-question-wire-options"
            XCTAssertEqual(q.isGroupAllow, isWire)
            XCTAssertEqual(GroupStore.approvalCard(for: event, in: g, questions: [q]), isWire ? .buttons(q) : .answerInWorkspace("Bank"))
            if name.hasPrefix("invalid") { XCTAssertFalse(q.isAllow) }
            let parse = (object["expect"] as? [String: Any])?["parse"] as? [String: String] ?? [:]
            for (input, expected) in parse { XCTAssertEqual(AnswerWord.parse(input)?.rawValue, expected) }
            if isWire {
                XCTAssertEqual(q.label("once"), "Allow once")
                XCTAssertEqual(q.label("always"), "Always allow tasks from Finance")
                XCTAssertEqual(q.label("no"), "No")
            }
        }
        XCTAssertEqual(AnswerWord.parse("  aLLoW \n once  "), .once)
        for invalid in ["Once", " once ", "Allow always", "Never", ""] { XCTAssertNil(AnswerWord.parse(invalid)) }
        for name in ["valid-group-approved-once", "valid-group-approved-always", "valid-group-denied-from-no"] {
            let map = try XCTUnwrap((try vectorObject(name)["expect"] as? [String: Any])?["map"] as? [String: Any])
            let answer = try XCTUnwrap(AnswerWord.parse(try XCTUnwrap(map["answer"] as? String)))
            XCTAssertEqual(answer.allowMode, map["allow_mode"] as? String)
            XCTAssertEqual(answer.approvedMode, map["approved_mode"] as? String)
            XCTAssertTrue(build([try vector(name)]).dropped.isEmpty)
        }
        XCTAssertEqual(build([try vector("invalid-group-approved-mode-permanent")]).dropped.first?.rule, "G11")
        let legacy = Question(message: QuestionMessage(schema: "orch.msg/1", id: "legacy", from: bank, to: "phones", type: "question", createdAt: "0", ticket: nil,
            body: QuestionBody(questionId: "relay:allow", title: nil, text: "Allow?", options: ["Once", "Always", "No"], recommended: nil)), workspaceName: "Bank")
        XCTAssertTrue(legacy.isAllow)
        XCTAssertTrue(legacy.isLegacyAllow)
        XCTAssertFalse(legacy.isGroupAllow)
    }
}
