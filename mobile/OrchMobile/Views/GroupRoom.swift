import SwiftUI

struct GroupRoomView: View {
    let key: GroupKey
    @Environment(AppModel.self) private var model
    @State private var members = false
    @State private var details = false
    @State private var reply: ReplyPreview?
    @State private var viewer: ArtifactItem?
    private var group: PhoneGroup? { model.groups.groups.first { $0.key == key } }

    var body: some View {
        Group {
            if let group {
                VStack(spacing: 0) {
                    header(group)
                    ScrollView {
                        LazyVStack(alignment: .leading, spacing: 12) {
                            if !group.startedHere { pill("Earlier messages are in \(group.hostName)") }
                            ForEach(Array(group.messages.enumerated()), id: \.element.id) { index, message in
                                if let seq = message.seq,
                                   group.gaps.contains(where: { gap in gap.upperBound <= seq && gap.lowerBound > (group.messages.prefix(index).compactMap(\.seq).max() ?? 0) }) {
                                    pill("a message is missing")
                                }
                                messageView(message, previous: index > 0 ? group.messages[index - 1] : nil, group: group)
                            }
                            TimelineView(.periodic(from: .now, by: 30)) { context in
                                ForEach(GroupRoomRules.thinking(group: group, now: context.date), id: \.self) { ws in
                                    Text("\(group.name(of: ws)) helper is thinking…").themeFont(13).foregroundStyle(Theme.muted)
                                }
                            }
                        }.padding(16)
                    }.accessibilityIdentifier("group-messages")
                    footer(group)
                }
                .onAppear { markRead(group) }
                .onChange(of: group.messages) { _, _ in markRead(group) }
                .sheet(isPresented: $members) { GroupMembersView(key: key) }
                .sheet(isPresented: $details) {
                    NavigationStack {
                        Text(privacy(group)).themeFont(17).padding(24).frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                            .background(Theme.bg).navigationTitle("Who sees this group?")
                            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { details = false } } }
                    }.presentationDetents([.medium])
                }
            } else { Text("This group is not on this phone.").foregroundStyle(Theme.muted) }
        }.background(Theme.bg).foregroundStyle(Theme.text).navigationBarTitleDisplayMode(.inline)
            .fullScreenCover(item: $viewer) { ArtifactViewer(item: $0) }
    }

    private func header(_ group: PhoneGroup) -> some View {
        HStack(spacing: 12) {
            Button { members = true } label: {
                HStack(spacing: 12) {
                    GroupBadges(group: group)
                    Text(group.title).themeFont(17, .semibold).multilineTextAlignment(.leading)
                }
            }.buttonStyle(PressStyle()).accessibilityIdentifier("group-members")
            Spacer(minLength: 0)
            Button { members = true } label: { Image(systemName: "info.circle").frame(width: 44, height: 44) }.accessibilityLabel("Members")
        }.padding(.horizontal, 16).padding(.bottom, 8)
            .overlay(alignment: .bottom) { Theme.border.frame(height: 1) }
            .safeAreaInset(edge: .bottom, spacing: 0) {
                if let ticket = group.ticket {
                    NavigationLink(value: ChatRoute.ticket(workspace: key.host, ticket: ticket)) {
                        Text("From ticket \(group.ticketKey ?? "") ›").themeFont(13).foregroundStyle(Theme.brand)
                    }.frame(maxWidth: .infinity, alignment: .leading).padding(.horizontal, 16).padding(.vertical, 8)
                }
            }
    }

    @ViewBuilder private func messageView(_ message: GroupMessage, previous: GroupMessage?, group: PhoneGroup) -> some View {
        if let event = message.event {
            if event.kind == "approval_needed" { GroupApprovalView(event: event, group: group, late: message.late) }
            else {
                let text = GroupRoomRules.eventText(event, group: group)
                if !text.isEmpty { pill(text) }
            }
        }
        if !message.quiet && !message.text.isEmpty && message.event == nil {
            let mine = isMine(message.sender)
            if !mine && (previous?.sender != message.sender || previous?.event != nil || previous?.quiet == true) {
                HStack(spacing: 6) {
                    WorkspaceBadge(name: senderName(message.sender, group: group), size: 24)
                    Text("\(senderName(message.sender, group: group)) helper").themeFont(13).foregroundStyle(Theme.muted)
                }
            }
            MessageBubble(item: ConvItem(id: message.id, at: message.at, side: mine ? .me : .them,
                                         text: message.text, label: phoneLabel(message.sender)),
                          conversationId: .topic(workspace: key.host, ticket: group.ticket ?? ""),
                          conversationLanguage: "en", workspaceName: senderName(message.sender, group: group),
                          quotedText: nil, onRetry: nil, onDiscard: nil, onOpenArtifact: { _ in })
        }
        if let task = message.task { GroupTaskView(task: group.tasks[task.delegate] ?? task, group: group) }
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
    private func pill(_ text: String) -> some View {
        Text(text).themeFont(13).foregroundStyle(Theme.muted).multilineTextAlignment(.center)
            .padding(.horizontal, 12).padding(.vertical, 8).background(Theme.surface2, in: Capsule())
            .frame(maxWidth: .infinity)
    }
    @ViewBuilder private func footer(_ group: PhoneGroup) -> some View {
        if group.closed {
            Text("This group is done. Read only.").themeFont(13).foregroundStyle(Theme.muted).padding(16)
        } else {
            let target: SendTarget? = GroupStore.replyTarget(in: group) == nil ? nil : group.ticket.map { .topic(workspace: key.host, ticket: $0) }
            VStack(spacing: 0) {
                Text("To: " + group.members.map { group.name(of: $0.ws) }.joined(separator: ", "))
                    .themeFont(13).foregroundStyle(Theme.muted).frame(maxWidth: .infinity, alignment: .leading).padding(.horizontal, 20)
                Composer(target: target, placeholder: "Message the group", reply: $reply, groupKey: key,
                         unavailableText: "Waiting for the first group message")
                Button { details = true } label: {
                    (Text("Everyone in this group sees what you write here · ").foregroundColor(Theme.muted) + Text("Details").foregroundColor(Theme.brand))
                        .themeFont(12).padding(.horizontal, 16).frame(minHeight: 44)
                }.accessibilityIdentifier("group-privacy")
            }
        }
    }
    private func markRead(_ group: PhoneGroup) { model.markRead(GroupRoomRules.readKey(group), items: GroupRoomRules.readItems(group)) }
    private func privacy(_ group: PhoneGroup) -> String {
        "Members see the group's messages from when they joined. They do not see the rest of the \(group.hostName) ticket."
    }
}

struct GroupTaskView: View {
    @Environment(AppModel.self) private var model
    let task: GroupTask
    let group: PhoneGroup
    var body: some View {
        let name = group.name(of: task.ws)
        VStack(alignment: .leading, spacing: 10) {
            HStack { WorkspaceBadge(name: name, size: 32); Text("Task for \(name)").themeFont(13).foregroundStyle(Theme.muted) }
            Text([task.key, task.title].compactMap { $0 }.joined(separator: " · ")).themeFont(17, .semibold)
            Text(GroupRoomRules.taskLabel(task.status, name: name)).themeFont(13).foregroundStyle(Theme.brand)
                .padding(.horizontal, 8).padding(.vertical, 3).background(Theme.brand.opacity(0.15), in: Capsule())
            if model.workspaces.contains(where: { $0.id == task.ws }), let ticket = task.ticket {
                NavigationLink(value: ChatRoute.ticket(workspace: task.ws, ticket: ticket)) {
                    Text("Open \(task.key ?? "ticket") ›").themeFont(15).foregroundStyle(Theme.brand).frame(minHeight: 44)
                }
            }
        }.padding(12).frame(maxWidth: .infinity, alignment: .leading)
            .background(Theme.surface, in: RoundedRectangle(cornerRadius: Theme.Radius.m))
            .overlay(RoundedRectangle(cornerRadius: Theme.Radius.m).stroke(Theme.borderStrong))
            .accessibilityIdentifier("group-task-\(task.delegate)")
    }
}

struct GroupApprovalView: View {
    @Environment(AppModel.self) private var model
    let event: GroupEvent
    let group: PhoneGroup
    var late: Bool = false
    @State private var sending = false
    private var result: GroupEvent? {
        guard let delegate = event.delegate else { return nil }
        return group.messages.compactMap(\.event).last { $0.delegate == delegate && ["approved", "denied"].contains($0.kind) }
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            if let result { Text(GroupRoomRules.eventText(result, group: group)).themeFont(15) }
            else if let questionId = event.questionMessage, let answer = model.answers[questionId] {
                Text(answer.lowercased() == "no" ? "You said no to \(group.name(of: event.ws ?? ""))" : "You allowed \(group.name(of: event.ws ?? "")) \(answer.lowercased() == "always" ? "always" : "once")").themeFont(15)
            } else {
                switch GroupStore.approvalCard(for: event, in: group, questions: model.questions, late: late) {
                case .buttons(let question):
                    Text(question.message.body.text).themeFont(17, .semibold)
                    if let answer = model.answers[question.id] { Text(answer).themeFont(13).foregroundStyle(Theme.muted) }
                    else if sending || model.queuedAnswers[question.id] != nil { Text("Waiting for approval").themeFont(13).foregroundStyle(Theme.muted) }
                    else if !group.closed {
                        HStack {
                            ForEach(question.message.body.options, id: \.self) { option in
                                Button(option.lowercased() == "once" || option.lowercased() == "allow once" ? "Allow once" : option.lowercased() == "always" ? "Always" : "No") {
                                    sending = true
                                    Task { await model.answer(question, with: option); sending = false }
                                }.themeFont(15, .medium).frame(maxWidth: .infinity, minHeight: 44)
                                    .background(Theme.surface3, in: RoundedRectangle(cornerRadius: Theme.Radius.s))
                            }
                        }
                    }
                case .answerInWorkspace(let name): Text("Answer in \(name)").themeFont(15)
                case .closed: Text("Answered").themeFont(15)
                }
            }
        }.padding(16).frame(maxWidth: .infinity, alignment: .leading)
            .background(Theme.surface2, in: RoundedRectangle(cornerRadius: Theme.Radius.m))
            .overlay(RoundedRectangle(cornerRadius: Theme.Radius.m).stroke(Theme.warn.opacity(0.35)))
            .accessibilityIdentifier("group-approval")
    }
}

struct GroupMembersView: View {
    let key: GroupKey
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    var body: some View {
        NavigationStack {
            ScrollView {
                if let group = model.groups.groups.first(where: { $0.key == key }) {
                    VStack(spacing: 20) {
                        GroupBadges(group: group)
                        Text(group.title).themeFont(24, .bold)
                        VStack(alignment: .leading, spacing: 16) {
                            Text("You · owner").themeFont(17)
                            ForEach(group.members, id: \.ws) { member in
                                Divider()
                                HStack(spacing: 12) {
                                    WorkspaceBadge(name: group.name(of: member.ws), icon: member.look?.icon, color: member.look?.color, size: 34, id: member.ws)
                                    Text(member.ws == key.host ? "\(group.name(of: member.ws)) · started the group from \(group.ticketKey ?? "")" : group.name(of: member.ws)).themeFont(15)
                                }
                            }
                        }.padding(16).frame(maxWidth: .infinity, alignment: .leading).background(Theme.surface, in: RoundedRectangle(cornerRadius: Theme.Radius.m))
                        Text("Members see the group's messages from when they joined. They do not see the rest of the \(group.hostName) ticket.").themeFont(15).foregroundStyle(Theme.muted)
                        Text("People removed keep the files they already fetched").themeFont(13).foregroundStyle(Theme.muted)
                    }.padding(16)
                }
            }.background(Theme.bg).foregroundStyle(Theme.text).navigationTitle("Members").navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
        }
    }
}
