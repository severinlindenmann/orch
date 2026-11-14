import XCTest
@testable import OrchMobile

final class GroupViewTests: XCTestCase {
    private let now = Date(timeIntervalSince1970: 1_800_000_000)
    private func snapshot(_ messages: [PhoneMessage]) -> GroupSnapshot {
        GroupStore.build(messages: messages.sorted { $0.message.createdAt > $1.message.createdAt }, workspaces: GroupMock.names,
                         ownPhoneId: "ph_iphone0001", ownMessageIds: [])
    }
    func testReviewNoteIsOncePerTaskAndUsesResolvedName() throws {
        let original = GroupMock.messages(now: now)
        let source = try XCTUnwrap(original.first { $0.message.body.task?.ws == GroupMock.home })
        func update(_ seq: Int, text: String, status: String = "working", kind: String = "working",
                    by: String = GroupMock.home, ws: String = GroupMock.home) -> PhoneMessage {
            var body = source.message.body
            body.text = text
            body.update = TextUpdate(kind: kind)
            body.group?.seq = seq
            body.by = by
            body.origin = GroupOrigin(id: "review-\(seq)", from: by, at: "now")
            body.task = GroupTask(delegate: "d_home", ws: ws, status: status)
            return PhoneMessage(message: TextMessage(id: "review-\(seq)", from: GroupMock.finance, to: "phones",
                type: "text", createdAt: ISO8601DateFormatter().string(from: now.addingTimeInterval(Double(seq))),
                ticket: GroupMock.ticket, body: body), workspaceName: "Finance")
        }
        let normal = try XCTUnwrap(GroupRoomRules.rows(snapshot(original)).first)
        XCTAssertNil(GroupRoomRules.reviewNote(task: try XCTUnwrap(normal.tasks["d_home"]), group: normal))
        let data = snapshot(original + [update(9, text: "Ready for review in Host-supplied name"),
                                        update(10, text: "Ready for review in Another name")])
        XCTAssertTrue(data.dropped.isEmpty)
        let group = try XCTUnwrap(GroupRoomRules.rows(data).first)
        let task = try XCTUnwrap(group.tasks["d_home"])
        XCTAssertEqual(task.status, "working")
        XCTAssertEqual(GroupRoomRules.reviewNote(task: task, group: group), "Ready for review in Home")
        XCTAssertEqual(group.messages.filter { $0.task?.delegate == task.delegate && GroupRoomRules.showsTaskCard($0, group: group) }.count, 1)
        XCTAssertTrue(group.messages.filter(GroupRoomRules.isReviewNote).allSatisfy(\.quiet))
        XCTAssertEqual(group.messages.filter(GroupRoomRules.isReviewNote).count, 2)
        XCTAssertNil(GroupRoomRules.reviewNote(task: try XCTUnwrap(group.tasks["d_bank"]), group: group))
        for sender in [GroupMock.bank, GroupMock.finance] {
            let otherData = snapshot(original + [update(9, text: "Ready for review in X", by: sender,
                                                        ws: sender == GroupMock.bank ? sender : GroupMock.home),
                                                 update(10, text: "Still working")])
            XCTAssertTrue(otherData.dropped.isEmpty)
            let other = try XCTUnwrap(GroupRoomRules.rows(otherData).first)
            XCTAssertNil(GroupRoomRules.reviewNote(task: try XCTUnwrap(other.tasks["d_home"]), group: other))
            if sender == GroupMock.finance {
                XCTAssertFalse(GroupRoomRules.isReviewNote(try XCTUnwrap(other.messages.first { $0.id == "review-9" })))
            }
        }
        for status in ["done", "failed"] {
            let finishedData = snapshot(original + [update(9, text: "Ready for review in X"),
                                                    update(10, text: "Finished", status: status)])
            XCTAssertTrue(finishedData.dropped.isEmpty)
            let finished = try XCTUnwrap(GroupRoomRules.rows(finishedData).first)
            XCTAssertEqual(finished.tasks["d_home"]?.status, status)
            XCTAssertNil(GroupRoomRules.reviewNote(task: try XCTUnwrap(finished.tasks["d_home"]), group: finished))
            // Even a stale card argument must use the current task status.
            XCTAssertNil(GroupRoomRules.reviewNote(task: task, group: finished))
        }
        for (status, kind) in [("done", "working"), ("working", "note")] {
            let other = try XCTUnwrap(GroupRoomRules.rows(snapshot(original + [update(9,
                text: "Ready for review in X", status: status, kind: kind)])).first)
            XCTAssertFalse(GroupRoomRules.isReviewNote(try XCTUnwrap(other.messages.last)))
            XCTAssertNil(GroupRoomRules.reviewNote(task: try XCTUnwrap(other.tasks["d_home"]), group: other))
        }
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
        XCTAssertEqual(GroupRoomRules.taskHeading(target: target), "Local")
        XCTAssertEqual(GroupRoomRules.taskHeading(target: GroupRoomRules.openTarget(task: task, workspaces: paired, tickets: [], updates: [update])), "Local update")
        XCTAssertNil(GroupRoomRules.openTarget(task: task, workspaces: paired, tickets: [], updates: []))
        XCTAssertNil(GroupRoomRules.openTarget(task: task, workspaces: [], tickets: [ticket], updates: [update]))
        XCTAssertEqual(GroupRoomRules.openTarget(task: task, workspaces: paired, tickets: [], updates: [update])?.label, "HOME-8")
        var noKey = update
        noKey.key = nil
        XCTAssertEqual(GroupRoomRules.openTarget(task: task, workspaces: paired, tickets: [], updates: [noKey])?.label, "topic")
        let wrongWorkspace = GroupTask(delegate: "d", ws: GroupMock.finance, ticket: "t_local", status: "working")
        let finance = Workspace(id: GroupMock.finance, name: "Finance", description: nil, tags: [], online: true, lastSeen: nil, openQuestions: 0)
        XCTAssertNil(GroupRoomRules.openTarget(task: wrongWorkspace, workspaces: [finance], tickets: [ticket], updates: [update]))
    }

    func testTaskHeadingUsesOnlyLocalTargetKeyAndTitle() {
        XCTAssertNil(GroupRoomRules.taskHeading(target: nil))
        XCTAssertEqual(GroupRoomRules.taskHeading(target: (GroupMock.home, "t", "HOME-7", "Local title")), "Local title")
        XCTAssertEqual(GroupRoomRules.taskHeading(target: (GroupMock.home, "t", "HOME-7", nil)), "Task")
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

    func testHeaderSubtitleAndFirstPillUseMemberNames() throws {
        let group = try XCTUnwrap(GroupRoomRules.rows(snapshot(GroupMock.messages(now: now))).first)
        XCTAssertEqual(GroupRoomRules.subtitle(group), "Finance, Home, Bank")
        XCTAssertEqual(GroupRoomRules.eventText(GroupEvent(kind: "created", ws: GroupMock.finance), group: group, ownAnswer: nil),
                       "Finance started this group")
        let note = GroupRoomRules.membersNote(group)
        XCTAssertTrue(note.hasSuffix("."))
        XCTAssertFalse(note.contains("ticket"))
    }

    func testRoomOpensAtNewestOpenApprovalCard() throws {
        let group = try XCTUnwrap(GroupRoomRules.rows(snapshot(GroupMock.messages(now: now))).first)
        let question = GroupMock.question(at: ISO8601DateFormatter().string(from: now))
        let card = try XCTUnwrap(group.messages.first { $0.event?.kind == "approval_needed" })
        XCTAssertEqual(GroupRoomRules.openRowID(group, questions: [question], answered: []), "m-" + card.id)
        XCTAssertNil(GroupRoomRules.openRowID(group, questions: [question], answered: [question.id]), "answered: open at the newest")
        XCTAssertNil(GroupRoomRules.openRowID(group, questions: [], answered: []), "not answerable here")
    }

    func testApprovalElsewhereLinksOnlyToAPairedMember() throws {
        let group = try XCTUnwrap(GroupRoomRules.rows(snapshot(GroupMock.messages(now: now))).first)
        let event = try XCTUnwrap(group.messages.compactMap(\.event).first { $0.kind == "approval_needed" })
        let paired = GroupRoomRules.answerElsewhere(event, group: group, paired: [GroupMock.bank])
        XCTAssertEqual(paired.text, "Answer in Bank")
        XCTAssertEqual(paired.route, .ticket(workspace: GroupMock.bank, ticket: "t_banktax001"))
        let other = GroupRoomRules.answerElsewhere(event, group: group, paired: [GroupMock.finance])
        XCTAssertNil(other.route)
        XCTAssertEqual(other.text, "Only someone with Bank on their phone can answer this.")
    }

    func testPendingGroupAnswerIsCancelledWhenTheGroupClosesOrTheCardIsLate() throws {
        let g = try XCTUnwrap(GroupRoomRules.rows(snapshot(GroupMock.messages(now: now))).first)
        let id = try XCTUnwrap(g.messages.compactMap(\.event).first { $0.kind == "approval_needed" }?.questionMessage)
        XCTAssertEqual(GroupRoomRules.answersToCancel([g], pending: [id], sending: []), [], "open group: keep it")
        let closed = PhoneGroup(key: g.key, title: g.title, members: g.members, hostName: g.hostName, names: g.names,
            externals: g.externals, ticketKey: g.ticketKey, ticket: g.ticket, messages: g.messages, closed: true,
            startedHere: g.startedHere, gaps: g.gaps, tasks: g.tasks)
        XCTAssertEqual(GroupRoomRules.answersToCancel([closed], pending: [id], sending: []), [id])
        XCTAssertEqual(GroupRoomRules.answersToCancel([closed], pending: [id], sending: [id]), [], "already sending")
        XCTAssertEqual(GroupRoomRules.answersToCancel([closed], pending: [], sending: []), [])
    }

    func testGroupApprovalQueuedAndVoiceOverTexts() {
        XCTAssertEqual(GroupApprovalView.queuedText("always"), "Always · waiting to send")
        XCTAssertEqual(GroupApprovalView.chosenAnnouncement("always"), "Always. Sent in a moment. Undo available.")
    }

    func testGroupApprovalPendingTextNamesTheChoice() {
        XCTAssertEqual(GroupApprovalView.pendingText("always", sending: false), "Always · sent in a moment")
        XCTAssertEqual(GroupApprovalView.pendingText("once", sending: true), "Allow once · sending…")
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

final class GroupBadgeLayoutTests: XCTestCase {
    func testSpotsStayInsideTheBox() {
        for members in [1, 2, 3, 5] {
            let spots = GroupBadgeLayout.spots(members: members)
            XCTAssertEqual(spots.count, min(members, 3))
            for spot in spots {
                XCTAssertGreaterThanOrEqual(spot.x, 0); XCTAssertGreaterThanOrEqual(spot.y, 0)
                XCTAssertLessThanOrEqual(spot.x + spot.size, GroupBadgeLayout.box)
                XCTAssertLessThanOrEqual(spot.y + spot.size, GroupBadgeLayout.box)
            }
        }
    }
    func testTriangleAndOverflow() {
        XCTAssertEqual(GroupBadgeLayout.spots(members: 3).map { [$0.x, $0.y] }, [[0, 1], [24, 1], [12, 24]])
        XCTAssertEqual(GroupBadgeLayout.spots(members: 5).last?.overflow, 3)
        XCTAssertNil(GroupBadgeLayout.spots(members: 3).last?.overflow)
        XCTAssertEqual(GroupBadgeLayout.spots(members: 1).first?.size, 46)
        XCTAssertEqual(GroupBadgeLayout.spots(members: 2).map(\.y), [12, 12])
    }
}
