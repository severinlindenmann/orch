import SwiftUI

struct GroupRoomView: View {
    let key: GroupKey
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.dismiss) private var dismiss
    @Environment(AppModel.self) private var model
    @State private var members = false
    @State private var details = false
    @State private var reply: ReplyPreview?
    @State private var viewer: ArtifactItem?
    /// The "group-bottom" marker is on screen (new rows then follow to the bottom).
    @State private var atBottom = true
    /// Message rows on screen now: read goes only up to the last of these while scrolled up.
    @State private var visible: Set<String> = []
    /// False until the room has scrolled to where it opens (an open approval card): the list starts at the bottom, and
    /// rows seen only in that first moment must not be marked read (P28 / P55).
    @State private var positioned = false
    /// "Open the … topic" in the info sheet: pushed once the sheet has closed, in whichever stack shows this room.
    @State private var openTopicAfterSheet = false
    @State private var topic: String?
    private var group: PhoneGroup? { model.groups.groups.first { $0.key == key } }

    var body: some View {
        Group {
            if let group {
                let rows = transcript(group)
                ScrollViewReader { proxy in
                    VStack(spacing: 0) {
                        header(group)
                        ScrollView {
                            LazyVStack(alignment: .leading, spacing: 12) {
                                if !group.startedHere { pill("Earlier messages are in \(group.hostName)") }
                                ForEach(Array(rows.enumerated()), id: \.element.id) { rowIndex, row in
                                    Group {
                                        switch row {
                                        case .message(let index, let message):
                                            if let seq = message.seq,
                                               group.gaps.contains(where: { gap in gap.upperBound <= seq && gap.lowerBound > (group.messages.prefix(index).compactMap(\.seq).max() ?? 0) }) {
                                                pill("a message is missing")
                                            }
                                            messageView(message, previous: rowIndex > 0 ? rows[rowIndex - 1].groupMessage : nil, group: group)
                                        case .outgoing(let item):
                                            outgoingView(item, group: group)
                                        }
                                    }.id(row.id)
                                    .onAppear { if let id = row.groupMessage?.id { visible.insert(id); markRead(group) } }
                                    .onDisappear { if let id = row.groupMessage?.id { visible.remove(id) } }
                                }
                                Color.clear.frame(height: 1).id("group-bottom")
                                    .onAppear { atBottom = true; markRead(group) }.onDisappear { atBottom = false }
                            }.padding(16)
                        }
                        .defaultScrollAnchor(.bottom).defaultScrollAnchor(.top, for: .alignment)
                        .scrollDismissesKeyboard(.interactively)
                        .accessibilityIdentifier("group-messages")
                        .safeAreaInset(edge: .bottom, spacing: 0) {
                            if !atBottom {
                                Button { scrollToBottom(proxy) } label: {
                                    JumpToLatestButton(count: model.readState.unread(GroupRoomRules.readKey(group), in: GroupRoomRules.readItems(group)))
                                }.buttonStyle(PressStyle()).frame(maxWidth: .infinity, alignment: .trailing).padding(12)
                            }
                        }
                        .onChange(of: rows.count) { old, new in
                            // Follow new rows only when already at the bottom or the newest row is this phone's own:
                            // someone reading older messages is not pulled away.
                            let own = rows.last.map { $0.isOutgoing || $0.groupMessage?.sender == .you } ?? false
                            if new > old, own || atBottom { scrollToBottom(proxy) }
                        }
                        // The bottom anchor alone lands short in a lazy list of rows with different heights: jump to the
                        // end marker once the rows are laid out (twice, as lazy rows settle their real heights).
                        // The newest open approval card wins over the newest message: the card lands just above the composer.
                        .task(id: key) {
                            let answered = Set(model.answers.keys).union(model.pendingAnswers.keys).union(model.queuedAnswers.keys)
                            let card = GroupRoomRules.openRowID(group, questions: model.questions, answered: answered)
                            if card == nil { positioned = true; markRead(group) }
                            let target = card ?? "group-bottom"
                            proxy.scrollTo(target, anchor: .bottom)
                            try? await Task.sleep(for: .milliseconds(300))
                            proxy.scrollTo(target, anchor: .bottom)
                            if !positioned {
                                await Task.yield()
                                // Opened at a card above the newest messages: the bottom marker has not reported leaving yet,
                                // so do not let a stale "at the bottom" mark the unseen messages read (P55). It reports itself
                                // again if it is really on screen.
                                if let card, card.hasPrefix("m-"),
                                   let at = group.messages.firstIndex(where: { "m-" + $0.id == card }) {
                                    atBottom = false
                                    // Rows seen while the list passed over its bottom are not on screen any more: only
                                    // messages up to the card count as seen.
                                    visible = visible.filter { id in (group.messages.firstIndex { $0.id == id } ?? 0) <= at }
                                }
                                positioned = true; markRead(group)
                            }
                        }
                        footer(group, onSent: { scrollToBottom(proxy) })
                    }
                }
                .onAppear { markRead(group) }
                .onChange(of: group.messages) { _, _ in markRead(group) }
                .sheet(isPresented: $members, onDismiss: {
                    if openTopicAfterSheet { openTopicAfterSheet = false; topic = group.ticket }
                }) { GroupMembersView(key: key, onOpenTopic: { openTopicAfterSheet = true }) }
                .navigationDestination(item: $topic) { ticket in
                    TicketChatView(workspaceId: key.host, ticketId: ticket).toolbar(.visible, for: .navigationBar)
                }
                .sheet(isPresented: $details) {
                    NavigationStack {
                        Text(privacy(group)).themeFont(17).padding(24).frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                            .background(Theme.bg).navigationTitle("Who sees this group?")
                            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { details = false } } }
                    }.presentationDetents([.medium])
                }
            } else { Text("This group is not on this phone.").foregroundStyle(Theme.muted) }
        }.background(Theme.bg).foregroundStyle(Theme.text).navigationBarTitleDisplayMode(.inline)
            .navigationBarBackButtonHidden(true)
            .toolbar(.hidden, for: .navigationBar)
            .fullScreenCover(item: $viewer) { ArtifactViewer(item: $0) }
    }

    private func transcript(_ group: PhoneGroup) -> [GroupTranscript.Row] {
        GroupTranscript.rows(messages: group.messages,
                             outgoing: model.conversationItems(.topic(workspace: key.host, ticket: group.ticket ?? "")))
    }

    private func outgoingView(_ item: ConvItem, group: PhoneGroup) -> some View {
        MessageBubble(item: item, conversationId: .topic(workspace: key.host, ticket: group.ticket ?? ""),
                      conversationLanguage: "en", workspaceName: group.hostName, quotedText: nil,
                      onRetry: { Task { await model.retrySend(item.clientId ?? "") } },
                      onDiscard: { model.discardSend(item.clientId ?? "") },
                      waitNote: QueuedNote.text(for: item.clientId.flatMap { model.outbox.item(clientId: $0) }), hugsContent: true)
    }

    /// Deferred: a scroll in the same update that adds the row runs before the lazy list has laid it out, and stops short
    /// of the new bubble (e2e P4.8). Scroll on the next turn and once more after the row has its real height.
    private func scrollToBottom(_ proxy: ScrollViewProxy) {
        Task { @MainActor in
            await Task.yield()
            jump(proxy)
            try? await Task.sleep(for: .milliseconds(300))
            jump(proxy)
        }
    }

    private func jump(_ proxy: ScrollViewProxy) {
        if reduceMotion { proxy.scrollTo("group-bottom", anchor: .bottom) }
        else { withAnimation(.easeOut(duration: 0.2)) { proxy.scrollTo("group-bottom", anchor: .bottom) } }
    }

    private func header(_ group: PhoneGroup) -> some View {
        HStack(spacing: 16) {
            Button { dismiss() } label: {
                Image(systemName: "chevron.left").frame(width: 44, height: 44)
                    .background(Theme.surface2, in: Circle())
            }.accessibilityLabel("Back").accessibilityIdentifier("group-back")
            GroupBadges(group: group).padding(.trailing, 10)
            VStack(alignment: .leading, spacing: 6) {
                Button { members = true } label: {
                    Text(group.title).themeFont(17, .semibold).lineLimit(1).truncationMode(.tail)
                }.accessibilityIdentifier("group-members")
                // Member names, like a messenger group; the topic link lives in the info screen.
                group.members.enumerated().reduce(Text("")) { text, entry in
                    text + Text(entry.offset == 0 ? "" : ", ") + group.memberText(entry.element.ws)
                }.themeFont(13).foregroundStyle(Theme.muted).lineLimit(1)
                    .accessibilityLabel(GroupRoomRules.subtitle(group)).accessibilityIdentifier("group-subtitle")
            }.frame(maxWidth: .infinity, alignment: .leading)
            if !group.closed {
                TimelineView(.everyMinute) { context in
                    ChatMuteButton(name: group.title, muted: model.isGroupMuted(key, now: context.date), groupStyle: true) { mute in
                        Task { await model.setGroupMute(key, mute) }
                    }
                }
            }
            Button { members = true } label: {
                Image(systemName: "info.circle").frame(width: 44, height: 44)
                    .background(Theme.surface2, in: Circle())
            }.accessibilityLabel("Group info")
        }.buttonStyle(PressStyle()).padding(.horizontal, 12).padding(.vertical, 12)
            .overlay(alignment: .bottom) { Theme.border.frame(height: 1) }
    }

    @ViewBuilder private func messageView(_ message: GroupMessage, previous: GroupMessage?, group: PhoneGroup) -> some View {
        if let event = message.event {
            if event.kind == "approval_needed" { GroupApprovalView(event: event, group: group, late: message.late) }
            else {
                let text = GroupRoomRules.eventText(event, group: group, ownAnswer: model.ownGroupAnswer(for: event, in: group))
                if !text.isEmpty { pill(text, external: group.isExternal(event.ws ?? "")) }
            }
        }
        if !message.quiet && !message.text.isEmpty && message.event == nil {
            let mine = isMine(message.sender)
            if !mine && (previous?.sender != message.sender || previous?.event != nil || previous?.quiet == true) {
                HStack(spacing: 6) {
                    switch message.sender {
                    case .host(let ws), .member(let ws), .person(let ws):
                        GroupMemberBadge(group: group, ws: ws, size: 24)
                        group.memberText(ws, suffix: "").themeFont(13).foregroundStyle(Theme.muted)
                    default:
                        Text(senderName(message.sender, group: group)).themeFont(13).foregroundStyle(Theme.muted)
                    }
                }
            }
            MessageBubble(item: ConvItem(id: message.id, at: message.at, side: mine ? .me : .them,
                                         text: message.text, label: phoneLabel(message.sender)),
                          conversationId: .topic(workspace: key.host, ticket: group.ticket ?? ""),
                          conversationLanguage: "en", workspaceName: senderName(message.sender, group: group),
                          quotedText: nil, onRetry: nil, onDiscard: nil, onOpenArtifact: { _ in }, hugsContent: true)
        }
        if let task = message.task, GroupRoomRules.showsTaskCard(message, group: group) { GroupTaskView(task: group.tasks[task.delegate] ?? task, group: group) }
        ForEach(message.ticketView?.attachments.filter { message.sharedFiles.contains($0.blobId ?? "") } ?? []) { attachment in
            Button {
                viewer = ArtifactItem(attachment, in: .topic(workspace: key.host, ticket: group.ticket ?? ""))
            } label: { AttachmentTile(attachment: attachment).padding(12).frame(maxWidth: .infinity, alignment: .leading).background(Theme.surface2, in: RoundedRectangle(cornerRadius: Theme.Radius.m)) }
                .buttonStyle(PressStyle()).accessibilityLabel("Open \(attachment.label ?? "file")")
        }
    }

    private func isMine(_ sender: GroupSender) -> Bool {
        switch sender {
        case .you: true
        case .host, .member, .person: false
        default: true // Other phone, when the sender model adds it.
        }
    }
    private func phoneLabel(_ sender: GroupSender) -> String? {
        switch sender {
        case .you, .host, .member, .person: nil
        default: "Other phone"
        }
    }
    private func senderName(_ sender: GroupSender, group: PhoneGroup) -> String {
        switch sender {
        case .you: "You"
        case .host(let ws), .member(let ws), .person(let ws): group.name(of: ws)
        default: "Other phone"
        }
    }
    private func pill(_ text: String, external: Bool = false) -> some View {
        (external ? Text(text).italic() : Text(text)).themeFont(13).foregroundStyle(Theme.muted).multilineTextAlignment(.center)
            .padding(.horizontal, 12).padding(.vertical, 8).background(Theme.surface2, in: Capsule())
            .frame(maxWidth: .infinity)
    }
    @ViewBuilder private func footer(_ group: PhoneGroup, onSent: @escaping () -> Void) -> some View {
        if group.closed {
            Text("Read only").themeFont(13).foregroundStyle(Theme.muted).padding(16)
        } else {
            let target: SendTarget? = GroupStore.replyTarget(in: group) == nil ? nil : group.ticket.map { .topic(workspace: key.host, ticket: $0) }
            VStack(spacing: 0) {
                TimelineView(.periodic(from: .now, by: 30)) { context in
                    let thinking = GroupRoomRules.thinking(group: group, now: context.date)
                    if !thinking.isEmpty {
                        VStack(alignment: .leading, spacing: 4) {
                            ForEach(thinking, id: \.self) { ws in
                                group.memberText(ws, suffix: " is thinking…").themeFont(13).foregroundStyle(Theme.muted)
                            }
                        }.frame(maxWidth: .infinity, alignment: .leading).padding(.horizontal, 20).padding(.bottom, 12)
                    }
                }
                group.members.enumerated().reduce(Text("To: ")) { text, entry in
                    text + Text(entry.offset == 0 ? "" : ", ") + group.memberText(entry.element.ws)
                }
                    .themeFont(13).foregroundStyle(Theme.muted).frame(maxWidth: .infinity, alignment: .leading).padding(.horizontal, 20).padding(.bottom, 8)
                Composer(target: target, placeholder: "Message the group", reply: $reply, onSent: onSent, groupKey: key,
                         unavailableText: "Waiting for the first group message")
                Button { details = true } label: {
                    (Text("Everyone in this group sees what you write here · ").foregroundColor(Theme.muted) + Text("Details").foregroundColor(Theme.brand))
                        .themeFont(12).padding(.horizontal, 16).frame(minHeight: 44)
                }.accessibilityIdentifier("group-privacy")
            }.accessibilityElement(children: .contain).accessibilityIdentifier("group-composer")
        }
    }
    private func markRead(_ group: PhoneGroup) {
        guard positioned else { return }
        let lastVisible = group.messages.last { visible.contains($0.id) }?.id
        model.markRead(GroupRoomRules.readKey(group), items: GroupRoomRules.readItems(group), atBottom: atBottom, lastVisibleId: lastVisible)
    }
    private func privacy(_ group: PhoneGroup) -> String { GroupRoomRules.membersNote(group) }
}

struct GroupTaskView: View {
    @Environment(AppModel.self) private var model
    let task: GroupTask
    let group: PhoneGroup
    var body: some View {
        let name = group.name(of: task.ws)
        let target = GroupRoomRules.openTarget(task: task, workspaces: model.workspaces, tickets: model.tickets, updates: model.updates)
        VStack(alignment: .leading, spacing: 10) {
            HStack { GroupMemberBadge(group: group, ws: task.ws, size: 32); group.memberText(task.ws, prefix: "Task for ").themeFont(13).foregroundStyle(Theme.muted) }
            if let heading = GroupRoomRules.taskHeading(target: target) {
                Text(heading).themeFont(17, .semibold)
            }
            (group.isExternal(task.ws) ? Text(GroupRoomRules.taskLabel(task.status, name: name)).italic().foregroundColor(Theme.muted) : Text(GroupRoomRules.taskLabel(task.status, name: name))).themeFont(13).foregroundStyle(Theme.brand)
                .padding(.horizontal, 8).padding(.vertical, 3).background(Theme.brand.opacity(0.15), in: Capsule())
            if let note = GroupRoomRules.reviewNote(task: task, group: group) {
                Text(note).themeFont(13).foregroundStyle(Theme.muted)
            }
            if let target {
                NavigationLink(value: ChatRoute.ticket(workspace: target.workspace, ticket: target.ticket)) {
                    Text("Open task ›").themeFont(15).foregroundStyle(Theme.brand).frame(minHeight: 44)
                }
            }
        }.padding(12).frame(maxWidth: .infinity, alignment: .leading)
            .background(Theme.surface, in: RoundedRectangle(cornerRadius: Theme.Radius.m))
            .overlay(RoundedRectangle(cornerRadius: Theme.Radius.m).stroke(Theme.borderStrong))
            .accessibilityElement(children: .contain)   // one card element; the id stays on it, not on every child
            .accessibilityIdentifier("group-task-\(task.delegate)")
    }
}

struct GroupApprovalView: View {
    @Environment(AppModel.self) private var model
    let event: GroupEvent
    let group: PhoneGroup
    var late: Bool = false
    @AccessibilityFocusState private var undoFocused: Bool
    private struct ApprovalOption: Identifiable { let id: String; let option: String; let label: String }
    /// The button word for a raw approval option; nil = unknown (no button).
    nonisolated static func approvalLabel(_ o: String) -> String? {
        switch o.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() {
        case "once", "allow once": "Allow once"
        case "always", "permanent": "Always"
        case "no", "deny": "No"
        default: nil
        }
    }
    /// The line under a chosen answer during the undo window (same window as topic answers), then while it is sent.
    nonisolated static func pendingText(_ answer: String, sending: Bool) -> String {
        let label = approvalLabel(answer) ?? answer
        return sending ? "\(label) · sending…" : "\(label) · sent in a moment"
    }
    /// An answer kept on this phone while offline: not done yet.
    nonisolated static func queuedText(_ answer: String) -> String { "\(approvalLabel(answer) ?? answer) · waiting to send" }
    /// VoiceOver: the buttons vanish on a tap, so say what happened and that it can still be undone.
    nonisolated static func chosenAnnouncement(_ answer: String) -> String { "\(approvalLabel(answer) ?? answer). Sent in a moment. Undo available." }
    private var result: GroupEvent? {
        guard let delegate = event.delegate else { return nil }
        return group.messages.compactMap(\.event).last { $0.delegate == delegate && ["approved", "denied"].contains($0.kind) }
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            if let result {
                let text = GroupRoomRules.eventText(result, group: group, ownAnswer: model.ownGroupAnswer(for: result, in: group))
                (group.isExternal(result.ws ?? "") ? Text(text).italic().foregroundColor(Theme.muted) : Text(text)).themeFont(15)
            } else if !group.closed, !late, let id = event.questionMessage, let answer = model.pendingAnswers[id],
                      let question = model.questions.first(where: { $0.id == id }) {
                let sending = model.sendingAnswers.contains(id)
                Text(question.message.body.text).themeFont(17, .semibold)
                HStack(spacing: 8) {
                    Text(Self.pendingText(answer, sending: sending)).themeFont(13).foregroundStyle(Theme.muted)
                        .accessibilityIdentifier("group-approval-pending")
                    Spacer(minLength: 0)
                    if !sending {
                        Button { model.undoAnswer(question) } label: {
                            Text("Undo").themeFont(15, .medium).foregroundStyle(Theme.brand)
                                .frame(minWidth: 44, minHeight: 44).contentShape(Rectangle())
                        }.accessibilityLabel("Undo \(Self.approvalLabel(answer) ?? answer)").accessibilityIdentifier("group-undo")
                            .accessibilityFocused($undoFocused)
                    }
                }
            } else if let id = event.questionMessage, let queued = model.queuedAnswers[id], model.answers[id] == nil {
                if let question = model.questions.first(where: { $0.id == id }) { Text(question.message.body.text).themeFont(17, .semibold) }
                Text(Self.queuedText(queued)).themeFont(13).foregroundStyle(Theme.muted).accessibilityIdentifier("group-approval-queued")
            } else if let answer = model.ownGroupAnswer(for: event, in: group) {
                switch Self.approvalLabel(answer) {
                case "No"?: group.memberText(event.ws ?? "", prefix: "You said no to ", suffix: "").themeFont(15)
                case "Always"?: group.memberText(event.ws ?? "", prefix: "You allowed ", suffix: " always").themeFont(15)
                case "Allow once"?: group.memberText(event.ws ?? "", prefix: "You allowed ", suffix: " once").themeFont(15)
                default: group.memberText(event.ws ?? "", prefix: "You answered \u{201C}\(answer)\u{201D} to ", suffix: "").themeFont(15)
                }
            } else {
                switch GroupStore.approvalCard(for: event, in: group, questions: model.questions, late: late) {
                case .buttons(let question):
                    Text(question.message.body.text).themeFont(17, .semibold)
                    if let answer = model.answers[question.id] { Text(answer).themeFont(13).foregroundStyle(Theme.muted) }
                    else if model.queuedAnswers[question.id] != nil { Text("Waiting for approval").themeFont(13).foregroundStyle(Theme.muted) }
                    else if !group.closed {
                        // Only options with a known meaning get a button (an unknown one must not read "No" and send itself).
                        let options = question.message.body.options.enumerated().compactMap { index, option in
                            Self.approvalLabel(option).map { ApprovalOption(id: "\(index)-\(option)", option: option, label: $0) }
                        }
                        HStack {
                            ForEach(options) { entry in
                                Button(entry.label) { choose(question, entry.option) }.themeFont(15, .medium).frame(maxWidth: .infinity, minHeight: 44)
                                    .background(Theme.surface3, in: RoundedRectangle(cornerRadius: Theme.Radius.s))
                            }
                        }
                    }
                case .answerInWorkspace:
                    let elsewhere = GroupRoomRules.answerElsewhere(event, group: group, paired: model.workspaces.map(\.id))
                    if let route = elsewhere.route {
                        NavigationLink(value: route) {
                            (Text(elsewhere.text) + Text(" ›")).themeFont(15, .medium).foregroundStyle(Theme.brand)
                                .frame(minHeight: 44, alignment: .leading)
                        }.accessibilityIdentifier("group-approval-elsewhere")
                    } else {
                        Text(elsewhere.text).themeFont(15).foregroundStyle(Theme.muted)
                    }
                case .closed: Text("Answered").themeFont(15)
                }
            }
        }.padding(16).frame(maxWidth: .infinity, alignment: .leading)
            .background(Theme.surface2, in: RoundedRectangle(cornerRadius: Theme.Radius.m))
            .overlay(RoundedRectangle(cornerRadius: Theme.Radius.m).stroke(Theme.warn.opacity(0.35)))
            // A container: without this the id is copied onto every child (the text, each button), so the card itself
            // was not one element and its buttons could not be found under it (e2e P4.3, VoiceOver).
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("group-approval")
    }

    private func choose(_ question: Question, _ option: String) {
        model.chooseAnswer(question, option)
        AccessibilityNotification.Announcement(Self.chosenAnnouncement(option)).post()
        Task { @MainActor in
            try? await Task.sleep(for: .milliseconds(150))
            undoFocused = true
        }
    }
}

struct GroupMembersView: View {
    let key: GroupKey
    var onOpenTopic: () -> Void = {}
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var note = false
    var body: some View {
        NavigationStack {
            ScrollView {
                if let group = model.groups.groups.first(where: { $0.key == key }) {
                    VStack(spacing: 20) {
                        GroupBadges(group: group)
                        Text(group.title).themeFont(24, .bold)
                        VStack(alignment: .leading, spacing: 16) {
                            row(subtitle: "Owner") {
                                Image(systemName: "person.fill").themeFont(15).foregroundStyle(Theme.brand)
                                    .frame(width: 34, height: 34).background(Theme.surface3, in: Circle()).accessibilityHidden(true)
                            } name: { Text("You") }
                            ForEach(group.members, id: \.ws) { member in
                                Divider()
                                row(subtitle: member.ws == key.host ? "Started the group" : nil) {
                                    GroupMemberBadge(group: group, ws: member.ws, size: 34)
                                } name: { group.memberText(member.ws) }
                            }
                        }.padding(16).frame(maxWidth: .infinity, alignment: .leading).background(Theme.surface, in: RoundedRectangle(cornerRadius: Theme.Radius.m))
                        if group.ticket != nil {
                            Button {
                                onOpenTopic()
                                dismiss()
                            } label: {
                                HStack {
                                    Text("Open the \(group.hostName) topic").themeFont(17)
                                    Spacer()
                                    ShellChevron()
                                }.frame(minHeight: 44).padding(.horizontal, 16).contentShape(Rectangle())
                                    .background(Theme.surface, in: RoundedRectangle(cornerRadius: Theme.Radius.m))
                            }.buttonStyle(PressStyle()).foregroundStyle(Theme.text).accessibilityIdentifier("group-open-topic")
                        }
                        // A disclosure: VoiceOver reads it as collapsed / expanded.
                        DisclosureGroup(isExpanded: $note) {
                            Text(GroupRoomRules.membersNote(group)).themeFont(13).foregroundStyle(Theme.muted)
                                .frame(maxWidth: .infinity, alignment: .leading).padding(.top, 4)
                        } label: {
                            Label("What members see", systemImage: "info.circle").themeFont(13).foregroundStyle(Theme.muted)
                                .frame(minHeight: 44)
                        }.tint(Theme.muted).accessibilityIdentifier("group-members-note")
                    }.padding(16)
                }
            }.background(Theme.bg).foregroundStyle(Theme.text).navigationTitle("Group info").navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
        }
    }

    private func row<Avatar: View>(subtitle: String?, @ViewBuilder avatar: () -> Avatar, name: () -> Text) -> some View {
        HStack(spacing: 12) {
            avatar()
            VStack(alignment: .leading, spacing: 2) {
                name().themeFont(15)
                if let subtitle { Text(subtitle).themeFont(13).foregroundStyle(Theme.muted) }
            }
        }
    }
}
