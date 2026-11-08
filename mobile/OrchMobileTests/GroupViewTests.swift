import XCTest
@testable import OrchMobile

final class GroupViewTests: XCTestCase {
    private let now = Date(timeIntervalSince1970: 1_800_000_000)
    private func snapshot(_ messages: [PhoneMessage]) -> GroupSnapshot {
        GroupStore.build(messages: messages.sorted { $0.message.createdAt > $1.message.createdAt }, workspaces: GroupMock.names,
                         ownPhoneId: "ph_iphone0001", ownMessageIds: [])
    }
    func testThinkingShowsAndExpires() throws {
        let group = try XCTUnwrap(GroupRoomRules.rows(snapshot(GroupMock.messages(now: now))).first)
        XCTAssertEqual(GroupRoomRules.thinking(group: group, now: now), [GroupMock.home])
        XCTAssertEqual(GroupRoomRules.thinking(group: group, now: now.addingTimeInterval(600)), [])
    }
    func testThinkingEndsOnLaterMemberText() throws {
        var messages = GroupMock.messages(now: now)
        let source = try XCTUnwrap(messages.first { $0.message.body.task != nil })
        var body = source.message.body
        body.update = nil; body.task = nil; body.text = "I found the letter."
        body.group?.seq = 9
        body.origin = GroupOrigin(id: "origin_result", from: GroupMock.home, at: ISO8601DateFormatter().string(from: now))
        messages.append(PhoneMessage(message: TextMessage(id: "m_groupresult001", from: GroupMock.finance, to: "phones", type: "text",
            createdAt: ISO8601DateFormatter().string(from: now), ticket: GroupMock.ticket, body: body, key: "FIN-14"), workspaceName: "Finance"))
        let group = try XCTUnwrap(GroupRoomRules.rows(snapshot(messages)).first)
        XCTAssertEqual(GroupRoomRules.thinking(group: group, now: now), [])
    }
    func testListSeparatesOpenAndHistoryAndFixturePassesRules() {
        let data = snapshot(GroupMock.messages(now: now))
        XCTAssertEqual(data.dropped, [])
        XCTAssertEqual(GroupRoomRules.rows(data).map(\.title), ["Pay car tax 2027"])
        XCTAssertEqual(GroupRoomRules.rows(data, closed: true).map(\.title), ["Pay car tax 2026"])
    }
    func testHistoryRowsAreNewestFirst() throws {
        let original = try XCTUnwrap(GroupMock.messages(now: now).first { $0.message.body.groupEvent?.kind == "closed" })
        let messages = ["2026-01-01T00:00:00Z", "2026-03-01T00:00:00Z", "2026-02-01T00:00:00Z"].enumerated().map { index, at in
            var body = original.message.body
            body.group = GroupInfo(id: "grp_t_history\(index)", host: GroupMock.finance, title: "History", members: body.group!.members, seq: 1)
            return PhoneMessage(message: TextMessage(id: "history-\(index)", from: GroupMock.finance, to: "phones", type: "text", createdAt: at,
                ticket: "t_history\(index)", body: body), workspaceName: "Finance")
        }
        XCTAssertEqual(GroupRoomRules.rows(snapshot(messages), closed: true).map(\.key.id),
                       ["grp_t_history1", "grp_t_history2", "grp_t_history0"])
    }

    func testOpenTargetRequiresPairingAndLocalTicketAndUsesLocalKey() throws {
        let task = GroupTask(delegate: "d", ws: GroupMock.home, ticket: "t_local", key: "FORGED-99", title: "Host title", status: "working")
        let paired = [Workspace(id: GroupMock.home, name: "Home", description: nil, tags: [], online: true, lastSeen: nil, openQuestions: 0)]
        let ticket = Ticket(id: "local", workspace: GroupMock.home, workspaceName: "Home", ticket: "t_local", title: "Local", text: "",
                            status: .working, kind: "working", at: "0", question: nil, key: "HOME-7")
        let update = TicketUpdate(id: "update", workspace: GroupMock.home, workspaceName: "Home", ticket: "t_local", kind: "working",
                                  title: "Local update", text: "", replyTo: nil, at: "0", key: "HOME-8")
        let target = try XCTUnwrap(GroupRoomRules.openTarget(task: task, workspaces: paired, tickets: [ticket], updates: []))
        XCTAssertEqual(target.workspace, GroupMock.home)
        XCTAssertEqual(target.ticket, "t_local")
        XCTAssertEqual(target.label, "HOME-7")
        XCTAssertEqual(GroupRoomRules.taskHeading(target: target), "HOME-7 · Local")
        XCTAssertEqual(GroupRoomRules.taskHeading(target: GroupRoomRules.openTarget(task: task, workspaces: paired, tickets: [], updates: [update])), "HOME-8 · Local update")
        XCTAssertNil(GroupRoomRules.openTarget(task: task, workspaces: paired, tickets: [], updates: []))
        XCTAssertNil(GroupRoomRules.openTarget(task: task, workspaces: [], tickets: [ticket], updates: [update]))
        XCTAssertEqual(GroupRoomRules.openTarget(task: task, workspaces: paired, tickets: [], updates: [update])?.label, "HOME-8")
        var noKey = update
        noKey.key = nil
        XCTAssertEqual(GroupRoomRules.openTarget(task: task, workspaces: paired, tickets: [], updates: [noKey])?.label, "ticket")
        let wrongWorkspace = GroupTask(delegate: "d", ws: GroupMock.finance, ticket: "t_local", status: "working")
        let finance = Workspace(id: GroupMock.finance, name: "Finance", description: nil, tags: [], online: true, lastSeen: nil, openQuestions: 0)
        XCTAssertNil(GroupRoomRules.openTarget(task: wrongWorkspace, workspaces: [finance], tickets: [ticket], updates: [update]))
    }

    func testTaskHeadingUsesOnlyLocalTargetKeyAndTitle() {
        XCTAssertNil(GroupRoomRules.taskHeading(target: nil))
        XCTAssertEqual(GroupRoomRules.taskHeading(target: (GroupMock.home, "t", "HOME-7", "Local title")), "HOME-7 · Local title")
        XCTAssertEqual(GroupRoomRules.taskHeading(target: (GroupMock.home, "t", "HOME-7", nil)), "HOME-7")
    }

    func testRowIDSeparatesHyphenatedHostAndID() throws {
        let g = try XCTUnwrap(snapshot(GroupMock.messages(now: now)).groups.first)
        func row(host: String, id: String) -> String {
            GroupListRow.rowID(PhoneGroup(key: GroupKey(host: host, id: id), title: g.title, members: g.members,
                hostName: g.hostName, names: g.names, externals: g.externals, ticketKey: g.ticketKey, ticket: g.ticket,
                messages: g.messages, closed: g.closed, startedHere: g.startedHere, gaps: g.gaps, tasks: g.tasks))
        }
        XCTAssertNotEqual(row(host: "a\u{0600}", id: "\u{0301}-z"), row(host: "a\u{0600}-\u{0301}", id: "z"))
        XCTAssertEqual(row(host: "a-b", id: "c"), "group-3-a-b-c")
        XCTAssertEqual(row(host: "a", id: "b-c"), "group-1-a-b-c")
        XCTAssertNotEqual(row(host: "a-b", id: "c"), row(host: "a", id: "b-c"))
    }

    func testTaskLabels() {
        let labels = ["waiting_start": "Waiting for Home to start", "waiting_approval": "Waiting for approval", "queued": "Queued",
                      "working": "Working", "done": "Done", "failed": "Failed", "denied": "No"]
        for (status, label) in labels { XCTAssertEqual(GroupRoomRules.taskLabel(status, name: "Home"), label) }
    }
    func testApprovalUsesBankQuestion() throws {
        let group = try XCTUnwrap(GroupRoomRules.rows(snapshot(GroupMock.messages(now: now))).first)
        let event = try XCTUnwrap(group.messages.compactMap(\.event).first { $0.kind == "approval_needed" })
        let question = GroupMock.question(at: ISO8601DateFormatter().string(from: now))
        XCTAssertEqual(GroupStore.approvalCard(for: event, in: group, questions: [question]), .buttons(question))
    }

    func testApprovalScopeUsesSanitizedPairedHostName() throws {
        var names = GroupMock.names
        names[GroupMock.finance] = "  Fin\u{200B}ance  "
        let data = GroupStore.build(messages: GroupMock.messages(now: now).sorted { $0.message.createdAt > $1.message.createdAt },
                                   workspaces: names, ownPhoneId: "ph_iphone0001", ownMessageIds: [])
        let group = try XCTUnwrap(data.groups.first { !$0.closed })
        XCTAssertEqual(group.hostName, "Finance")
        let event = try XCTUnwrap(group.messages.compactMap(\.event).first { $0.kind == "approval_needed" })
        let question = GroupMock.question(at: "now")
        XCTAssertEqual(GroupStore.approvalCard(for: event, in: group, questions: [question]), .buttons(question))
        let q = question.message
        var body = q.body
        body.scope = "tasks from Fin\u{200B}ance"
        let spoofed = Question(message: QuestionMessage(schema: q.schema, id: q.id, from: q.from, to: q.to, type: q.type,
            createdAt: q.createdAt, ticket: q.ticket, body: body), workspaceName: question.workspaceName)
        XCTAssertEqual(GroupStore.approvalCard(for: event, in: group, questions: [spoofed]), .answerInWorkspace("Bank"))
    }

    func testExternalMemberPresentationUsesProvenanceAndTransport() throws {
        let data = GroupStore.build(messages: GroupMock.messages(now: now), workspaces: [GroupMock.finance: "Finance"],
                                    ownPhoneId: "ph_iphone0001", ownMessageIds: [])
        let group = try XCTUnwrap(GroupRoomRules.rows(data).first)
        XCTAssertTrue(group.isExternal(GroupMock.home))
        XCTAssertEqual(group.name(of: GroupMock.home), "Home · via Finance")
        let left = GroupEvent(kind: "member_left", ws: GroupMock.home, name: "You")
        XCTAssertEqual(GroupRoomRules.eventText(left, group: group, ownAnswer: nil), "Home · via Finance left this group")
        XCTAssertEqual(GroupRoomRules.eventText(GroupEvent(kind: "approved", ws: GroupMock.home, mode: "once"), group: group, ownAnswer: "Once"),
                       "You allowed Home · via Finance once")
        let badge = GroupRoomRules.badgeName(group: group, ws: GroupMock.home)
        XCTAssertNotEqual(badge, group.name(of: GroupMock.home))
        let paired = try XCTUnwrap(GroupRoomRules.rows(snapshot(GroupMock.messages(now: now))).first)
        XCTAssertEqual(GroupRoomRules.badgeName(group: paired, ws: GroupMock.home), "Home")
        for message in group.messages where message.sender == .member(GroupMock.home) && !message.quiet {
            let item = try XCTUnwrap(GroupRoomRules.readItems(group).first { $0.id == message.id })
            if case .theirs = item.kind {} else { XCTFail("External member must remain incoming") }
        }
    }

    func testApprovalEventTextUsesOnlyOwnAnswer() throws {
        let group = try XCTUnwrap(GroupRoomRules.rows(snapshot(GroupMock.messages(now: now))).first)
        for mode in ["once", "always"] {
            let approved = GroupEvent(kind: "approved", ws: GroupMock.home, mode: mode)
            XCTAssertEqual(GroupRoomRules.eventText(approved, group: group, ownAnswer: mode), "You allowed Home \(mode)")
            XCTAssertEqual(GroupRoomRules.eventText(approved, group: group, ownAnswer: nil), "Home allowed Finance \(mode)")
        }
        let denied = GroupEvent(kind: "denied", ws: GroupMock.home)
        XCTAssertEqual(GroupRoomRules.eventText(denied, group: group, ownAnswer: "No"), "You said no to Home")
        XCTAssertEqual(GroupRoomRules.eventText(denied, group: group, ownAnswer: nil), "Home said no")
    }

    @MainActor func testGroupSendUsesNewestHostCopy() async throws {
        let defaults = UserDefaults.standard
        let previous = defaults.object(forKey: "mockGroups")
        defaults.set(true, forKey: "mockGroups")
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer {
            defaults.set(previous, forKey: "mockGroups")
            Keychain.delete()
            try? FileManager.default.removeItem(at: dir)
        }
        Keychain.delete()
        let model = AppModel(useMock: true, voiceMode: .scripted, outboxDirectory: dir, speechCache: dir.appendingPathComponent("speech"), systemAudioControls: false)
        model.openSampleInvite()
        await model.connect(phoneName: "Test")
        await model.finishSetup(allowNotifications: false)
        let group = try XCTUnwrap(GroupRoomRules.rows(model.groups).first)
        try await model.sendGroup(MessageDraft(text: "Please check the payment.", replyTo: "stale"), key: group.key)
        let mock = try XCTUnwrap(model.mock)
        let requests = await mock.requests
        let request = try XCTUnwrap(requests.last)
        XCTAssertEqual(request.to, GroupMock.finance)
        XCTAssertEqual(request.ticket, GroupMock.ticket)
        XCTAssertEqual(request.replyTo, GroupStore.replyTarget(in: group))
        XCTAssertEqual(request.replyTo, "m_groupcopy00008")

        // G8: a quote in the normal ticket composer cannot opt into group fan-out.
        await mock.setOffline(true)
        let copyIds = group.messages.filter {
            $0.message.message.from == group.key.host && $0.message.message.to == "phones"
        }.map(\.id)
        XCTAssertFalse(copyIds.isEmpty)
        for copyId in copyIds {
            XCTAssertTrue(model.isGroupCopy(copyId))
            let plain = try await model.send(MessageDraft(text: "Ticket only", replyTo: copyId),
                                             to: .topic(workspace: group.key.host, ticket: GroupMock.ticket))
            XCTAssertNil(try XCTUnwrap(model.outbox.item(clientId: plain.clientId)).replyTo)
        }
        let other = "m_plainreply0001"
        XCTAssertFalse(model.isGroupCopy(other))
        let plain = try await model.send(MessageDraft(text: "Quoted ticket reply", replyTo: other),
                                         to: .topic(workspace: group.key.host, ticket: GroupMock.ticket))
        XCTAssertEqual(try XCTUnwrap(model.outbox.item(clientId: plain.clientId)).replyTo, other)
        let grouped = try await model.sendGroup(MessageDraft(text: "Group reply", replyTo: other), key: group.key)
        let queued = try XCTUnwrap(model.outbox.item(clientId: grouped.clientId))
        XCTAssertEqual(queued.replyTo, "m_groupcopy00008")
        XCTAssertEqual(queued.ticket, GroupMock.ticket)
    }
}
