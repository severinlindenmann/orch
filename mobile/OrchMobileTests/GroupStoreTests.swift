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

    private func message(_ id: String, seq: Int? = nil, at: String = "10", host: String? = nil,
                         from: String? = nil, to: String = "phones", ticket: String? = "t_fin14a", edit: (inout TextBody) -> Void = { _ in }) -> PhoneMessage {
        let host = host ?? finance
        var body = TextBody(text: id, group: GroupInfo(id: "grp_t_fin14a", host: host, title: "Tax", members: members, seq: seq))
        edit(&body)
        return PhoneMessage(message: TextMessage(id: id, from: from ?? host, to: to, type: "text", createdAt: at,
            ticket: ticket, body: body, key: "FIN-14"), workspaceName: workspaces[host] ?? "Unknown")
    }

    /// Fixtures are written oldest first for readability; the phone API supplies newest first.
    private func build(_ oldestFirst: [PhoneMessage], own: Set<String> = []) -> GroupSnapshot {
        GroupStore.build(messages: oldestFirst.reversed(), workspaces: workspaces, ownPhoneId: phone, ownMessageIds: own)
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
        XCTAssertEqual(joined.gaps, [2, 3, 4]) // Phones do not begin at a member's from_seq.
        let quiet = try group([vector("valid-fanout-phones-quiet")])
        XCTAssertEqual(quiet.messages.first?.sender, .member(home))
        XCTAssertEqual(quiet.messages.first?.quiet, true)
        XCTAssertNil(quiet.lastLine)
        let file = try group([vector("valid-phone-copy-with-file")])
        XCTAssertEqual(file.messages.first?.sharedFiles, ["b_bill2027pdf00001"])
        XCTAssertEqual(file.messages.first?.ticketView?.attachments.first?.blobId, "b_bill2027pdf00001")
        XCTAssertEqual(file.messages.first?.message.message.body.toPerson, true)

        let cases = [("invalid-copy-you-not-from-phone", "G4"), ("invalid-too-many-members", "limit"),
                     ("invalid-group-host-mismatch", "G3"), ("invalid-group-id-not-host-ticket", "G1"),
                     ("invalid-group-event-from-member", "G3"), ("invalid-member-speaks-as-you", "G4")]
        for (name, rule) in cases {
            // The host-mismatch vector's from equals host, but that host is unpaired. G7 is tested separately.
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

    func testHostCollisionAndRejectedMessagesDoNotClaimAnId() throws {
        let first = message("first"), second = message("second", host: home)
        let snapshot = build([first, second])
        XCTAssertEqual(snapshot.groups.map(\.key), [GroupKey(host: finance, id: "grp_t_fin14a")])
        XCTAssertEqual(snapshot.dropped.map(\.rule), ["G7"])
        let invalid = message("bad", host: finance) { $0.by = "you" }
        XCTAssertEqual(build([invalid, second]).groups.first?.key.host, home)
        XCTAssertEqual(build([second, first]).groups.first?.key.host, home)
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
        XCTAssertEqual(build([other], own: ["sent"]).groups.first?.messages.first?.sender, .you)
        let dashboard = message("dashboard") {
            $0.by = "you"; $0.via = "dashboard"; $0.origin = GroupOrigin(id: "dash", from: "dashboard", at: "09")
        }
        XCTAssertEqual(try group([dashboard]).lastLine, "You: dashboard")
        XCTAssertEqual(build([message("forged", from: home) { $0.by = "you" }]).dropped.first?.rule, "G4")
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
        for (supplied, expected) in [("You", "Workspace"), ("  yOu \n", "Workspace"), ("  ", "Workspace"), ("Guest", "Guest")] {
            let m = message("text") {
                $0.by = outsider
                $0.group = GroupInfo(id: "grp_t_fin14a", host: self.finance, title: "Tax",
                    members: [GroupMember(ws: self.finance, name: "Fake host"),
                              GroupMember(ws: self.home, name: "You"), GroupMember(ws: outsider, name: supplied)])
            }
            let g = try group([m])
            XCTAssertEqual(g.names, [finance: "Finance", home: "Home", outsider: expected])
            XCTAssertEqual(g.name(of: home), "Home")
            XCTAssertEqual(g.lastLine, "\(expected): text")
        }
        let paired = message("paired") { $0.by = self.home }
        for name in ["", "  You ", " \n"] {
            let snapshot = GroupStore.build(messages: [paired], workspaces: [finance: "Finance", home: name],
                                            ownPhoneId: phone, ownMessageIds: [])
            XCTAssertEqual(snapshot.groups.first?.lastLine, "Workspace: paired")
        }
    }

    func testGroupRequiresMatchingNonNilTicket() {
        for ticket: String? in [nil, "wrong"] {
            let snapshot = build([message("invalid", ticket: ticket)])
            XCTAssertEqual(snapshot.dropped.map(\.rule), ["G1"])
            XCTAssertTrue(snapshot.groups.isEmpty)
        }
        XCTAssertTrue(build([message("valid")]).dropped.isEmpty)
    }

    func testHiddenEchoStillRegistersHostTaskAndClosure() throws {
        let echo = message("echo") { $0.echoOf = "sent"; $0.phone = self.phone }
        let collision = build([echo, message("collision", host: home)], own: ["sent"])
        XCTAssertEqual(collision.dropped.map(\.rule), ["G7"])
        XCTAssertTrue(collision.groups.isEmpty)

        let taskEcho = message("task-echo") {
            $0.echoOf = "sent"; $0.phone = self.phone
            $0.task = GroupTask(delegate: "d", ws: self.home, status: "done")
        }
        let backwards = message("backwards") {
            $0.task = GroupTask(delegate: "d", ws: self.home, status: "working")
        }
        let tasks = build([message("visible"), taskEcho, backwards], own: ["sent"])
        XCTAssertEqual(tasks.dropped.map(\.rule), ["G9"])
        XCTAssertEqual(tasks.groups.first?.tasks["d"]?.status, "done")
        XCTAssertEqual(tasks.groups.first?.messages.map(\.id), ["visible"])

        let closeEcho = message("close-echo") {
            $0.echoOf = "sent"; $0.phone = self.phone; $0.groupEvent = GroupEvent(kind: "closed")
        }
        let closed = build([message("visible"), closeEcho, message("late")], own: ["sent"])
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
        let duplicate = message("copy") { $0.origin = GroupOrigin(id: "origin", from: self.finance, at: "09") }
        let snapshot = build([first, first, duplicate])
        XCTAssertTrue(snapshot.dropped.isEmpty)
        XCTAssertEqual(snapshot.groups.first?.messages.map(\.id), ["first"])
        XCTAssertEqual(snapshot.groups.first?.startedHere, false)
        XCTAssertEqual(snapshot.groups.first?.hostName, "Finance")
    }

    func testSequenceOrderTimeInsertionGapsAndNewestMembers() throws {
        let latest = message("s5", seq: 5, at: "30") {
            $0.group = GroupInfo(id: "grp_t_fin14a", host: self.finance, title: "New title",
                                members: self.members + [GroupMember(ws: self.bank, name: "Bank")], seq: 5)
        }
        let g = try group([message("before", at: "00"), message("s2", seq: 2, at: "10"),
                           message("b", at: "20"), message("a", at: "20"), latest,
                           message("s1", seq: 1, at: "40"), message("after", at: "50")])
        XCTAssertEqual(g.messages.map(\.id), ["before", "s1", "s2", "a", "b", "s5", "after"])
        XCTAssertEqual(g.gaps, [3, 4])
        XCTAssertEqual(g.members.last?.ws, bank)
        XCTAssertEqual(g.title, "New title")
        XCTAssertEqual(g.ticketKey, "FIN-14")
        let equalSeq = message("renamed", seq: 5, at: "60") {
            $0.group = GroupInfo(id: "grp_t_fin14a", host: self.finance, title: "Renamed", members: self.members, seq: 5)
        }
        XCTAssertEqual(try group([latest, equalSeq]).title, "Renamed")
        XCTAssertEqual(try group([message("b", at: "10"), message("a", at: "10")]).messages.map(\.id), ["a", "b"])
    }

    func testEventsQuietAndClosure() throws {
        let start = message("start", seq: 1) { $0.groupEvent = GroupEvent(kind: "created") }
        let close = message("close", seq: 2) { $0.groupEvent = GroupEvent(kind: "closed") }
        let closeAgain = message("closed-again", seq: 3) { $0.groupEvent = GroupEvent(kind: "closed") }
        let snapshot = build([start, close, message("late"), closeAgain])
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
        func task(_ id: String, _ status: String, by: String? = nil, ws: String? = nil) -> PhoneMessage {
            message(id) {
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
        let closed = try group([message("copy"), message("close") { $0.groupEvent = GroupEvent(kind: "closed") }])
        XCTAssertNil(GroupStore.replyTarget(in: closed))
        XCTAssertNil(GroupStore.replyTarget(in: try group([message("targeted", to: home)])))
        // A real phone reply has no group; it stays in the ordinary ticket chat.
        let own = try vector("valid-phone-text-optin-reply")
        XCTAssertEqual(GroupStore.replyTarget(in: try group([message("copy"), own])), "copy")
    }

    func testApprovalRequiresTheOpenMemberQuestionAndEveryCondition() throws {
        let g = try group([message("group") {
            $0.group = GroupInfo(id: "grp_t_fin14a", host: self.finance, title: "Tax",
                                members: self.members + [GroupMember(ws: self.bank, name: "You")])
        }])
        let event = GroupEvent(kind: "approval_needed", ws: bank, delegate: "d", questionMessage: "q")
        func question(id: String = "q", from: String? = nil, options: [String] = ["Allow once", "Always", "No"],
                      scope: String? = "Tasks from FINANCE") -> Question {
            Question(message: QuestionMessage(schema: "orch.msg/1", id: id, from: from ?? bank, to: "phones", type: "question",
                createdAt: "10", ticket: nil, body: QuestionBody(questionId: "relay:allow", title: nil, text: "Allow?",
                options: options, recommended: nil, scope: scope)), workspaceName: "Bank")
        }
        func card(_ questions: [Question], event e: GroupEvent? = nil) -> ApprovalCard {
            GroupStore.approvalCard(for: e ?? event, in: g, questions: questions)
        }
        XCTAssertEqual(card([question()]), .buttons(question()))
        let once = question(options: ["Once", "Always", "No"])
        XCTAssertEqual(card([once]), .buttons(once))
        for q in [question(id: "wrong"), question(from: finance), question(options: ["Always", "No"]),
                  question(options: ["Allow once", "No"]), question(scope: nil), question(scope: "Tasks from Home"),
                  question(scope: "Tasks from Finance Office"), question(scope: "Allow tasks from Finance")] {
            XCTAssertEqual(card([q]), .answerInWorkspace("Bank"))
        }
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
}
