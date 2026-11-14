import SwiftUI

enum GroupRoomRules {
    static func isReviewNote(_ message: GroupMessage) -> Bool {
        guard let task = message.task, message.sender == .member(task.ws) else { return false }
        return message.message.message.type == "text" &&
        message.message.message.body.update?.kind == "working" &&
        message.task?.status == "working" && message.text.hasPrefix("Ready for review in ")
    }

    static func reviewNote(task: GroupTask, group: PhoneGroup) -> String? {
        guard group.tasks[task.delegate]?.status == "working",
              group.messages.contains(where: {
                  $0.sender == .member(task.ws) && $0.task?.ws == task.ws &&
                  $0.task?.delegate == task.delegate && isReviewNote($0)
              }) else { return nil }
        return "Ready for review in \(group.name(of: task.ws))"
    }

    static func showsTaskCard(_ message: GroupMessage, group: PhoneGroup) -> Bool {
        guard let task = message.task else { return false }
        return group.messages.first(where: { $0.task?.delegate == task.delegate })?.id == message.id
    }

    static func openTarget(task: GroupTask, workspaces: [Workspace], tickets: [Ticket], updates: [TicketUpdate])
        -> (workspace: String, ticket: String, label: String, title: String?)? {
        guard workspaces.contains(where: { $0.id == task.ws }), let ticket = task.ticket else { return nil }
        if let local = tickets.first(where: { $0.workspace == task.ws && $0.ticket == ticket }) {
            return (task.ws, ticket, local.key ?? "topic", local.title)
        }
        if let local = updates.first(where: { $0.workspace == task.ws && $0.ticket == ticket }) {
            return (task.ws, ticket, local.key ?? "topic", local.title)
        }
        return nil
    }

    static func taskHeading(target: (workspace: String, ticket: String, label: String, title: String?)?) -> String? {
        guard let target else { return nil }
        return target.title ?? "Task"
    }

    static func badgeName(group: PhoneGroup, ws: String) -> String {
        guard group.isExternal(ws) else { return group.name(of: ws) }
        let hash = Look.djb2(ws)
        let letter = UnicodeScalar(65 + hash % 26)!
        return String(letter) + String(hash, radix: 16)
    }

    static func rows(_ snapshot: GroupSnapshot, closed: Bool = false) -> [PhoneGroup] {
        snapshot.groups.filter { $0.closed == closed }.sorted { ($0.messages.last?.at ?? "") > ($1.messages.last?.at ?? "") }
    }

    static func thinking(group: PhoneGroup, now: Date) -> [String] {
        guard !group.closed else { return [] }
        var working: [String: Date] = [:]
        for message in group.messages {
            let ws: String
            switch message.sender {
            case .host(let id), .member(let id): ws = id
            default: continue
            }
            guard group.members.contains(where: { $0.ws == ws }) else { continue }
            let kind = message.message.message.body.update?.kind
            if kind == "working" {
                working[ws] = SharedISO.isoFraction.date(from: message.at) ?? SharedISO.iso.date(from: message.at)
            } else if kind != "ack", !message.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                working[ws] = nil
            }
        }
        return group.members.compactMap { member in
            guard let at = working[member.ws], now.timeIntervalSince(at) < 600 else { return nil }
            return member.ws
        }
    }

    static func taskLabel(_ status: String, name: String) -> String {
        switch status {
        case "waiting_start": "Waiting for \(name) to start"
        case "waiting_approval": "Waiting for approval"
        case "queued": "Queued"
        case "working": "Working"
        case "done": "Done"
        case "failed": "Failed"
        case "denied": "No"
        default: "Waiting for \(name) to start"
        }
    }

    /// A member's question in this group is still open (by question message id).
    static func needsYou(_ group: PhoneGroup, open: Set<String>) -> Bool {
        group.messages.contains { m in [m.task?.questionMessage, m.event?.questionMessage].contains { $0.map(open.contains) == true } }
    }
    static func readKey(_ group: PhoneGroup) -> String { "group:\(group.key.host)|\(group.key.id)" }
    static func readItems(_ group: PhoneGroup) -> [ChatItem] {
        group.messages.map { message in
            let incoming: Bool
            switch message.sender { case .you: incoming = false; default: incoming = true }
            return ChatItem(id: message.id, at: message.at, kind: incoming && !message.quiet ? .theirs(message.text, label: nil) : .mine(message.text, queued: false))
        }
    }

    /// Header subtitle: the member names, as a messenger group shows them.
    static func subtitle(_ group: PhoneGroup) -> String { group.members.map { group.name(of: $0.ws) }.joined(separator: ", ") }

    static func membersNote(_ group: PhoneGroup) -> String {
        "Members see the group's messages from when they joined. They do not see the rest of the \(group.hostName) topic. People removed keep the files they already fetched."
    }

    /// The row id ("m-" + message id) of the newest approval card this phone can still answer; the room opens there.
    static func openRowID(_ group: PhoneGroup, questions: [Question], answered: Set<String>) -> String? {
        guard !group.closed else { return nil }
        let decided = Set(group.messages.compactMap(\.event).filter { ["approved", "denied"].contains($0.kind) }.compactMap(\.delegate))
        return group.messages.last { message in
            guard let event = message.event, event.kind == "approval_needed", let delegate = event.delegate, !decided.contains(delegate),
                  case .buttons(let question) = GroupStore.approvalCard(for: event, in: group, questions: questions, late: message.late)
            else { return false }
            return !answered.contains(question.id)
        }.map { "m-" + $0.id }
    }

    /// Answers still in their undo window whose group card can no longer be answered (group closed, or the card came
    /// late): they are dropped, not sent. One already sending is left alone.
    static func answersToCancel(_ groups: [PhoneGroup], pending: Set<String>, sending: Set<String>) -> Set<String> {
        guard !pending.isEmpty else { return [] }
        var out: Set<String> = []
        for group in groups {
            for message in group.messages {
                guard let event = message.event, event.kind == "approval_needed", let id = event.questionMessage,
                      pending.contains(id), !sending.contains(id), group.closed || message.late else { continue }
                out.insert(id)
            }
        }
        return out
    }

    /// An approval this phone cannot answer: link to the member's topic (or chat) when it is paired here, else say who answers.
    static func answerElsewhere(_ event: GroupEvent, group: PhoneGroup, paired: [String]) -> (route: ChatRoute?, text: String) {
        let ws = event.ws ?? ""
        let name = group.name(of: ws)
        guard paired.contains(ws), !group.isExternal(ws) else {
            return (nil, "Only someone with \(name) on their phone can answer this.")
        }
        if let delegate = event.delegate, let ticket = group.tasks[delegate]?.ticket {
            return (.ticket(workspace: ws, ticket: ticket), "Answer in \(name)")
        }
        return (.workspace(ws), "Answer in \(name)")
    }

    static func eventText(_ event: GroupEvent, group: PhoneGroup, ownAnswer: String?) -> String {
        let name = group.name(of: event.ws ?? "")
        switch event.kind {
        case "created": return "\(group.hostName) started this group"
        case "member_added": return "\(group.hostName) added \(name) to this group"
        case "member_left": return "\(name) left this group"
        case "approved":
            let mode = event.mode == "always" ? "always" : "once"
            return ownAnswer != nil ? "You allowed \(name) \(mode)" : "\(name) allowed \(group.hostName) \(mode)"
        case "denied": return ownAnswer != nil ? "You said no to \(name)" : "\(name) said no"
        case "closed": return "This group is done"
        default: return ""
        }
    }
}

extension AppModel {
    func ownGroupAnswer(for event: GroupEvent, in group: PhoneGroup) -> String? {
        guard let delegate = event.delegate,
              let questionId = group.messages.compactMap(\.event).last(where: {
                  $0.kind == "approval_needed" && $0.delegate == delegate
              })?.questionMessage,
              !answeredElsewhere.contains(questionId) else { return nil }
        return answers[questionId] ?? pendingAnswers[questionId] ?? queuedAnswers[questionId]
    }

    /// Resolve again at send time: every text opts in using the newest host copy.
    @discardableResult
    func sendGroup(_ draft: MessageDraft, key: GroupKey) async throws -> OutboxItem {
        guard let group = groups.groups.first(where: { $0.key == key }),
              let ticket = group.ticket, let reply = GroupStore.replyTarget(in: group) else {
            throw SendRequest.Problem.badTarget
        }
        var draft = draft
        draft.replyTo = reply
        return try await sendInternal(draft, to: .topic(workspace: key.host, ticket: ticket))
    }
}

struct GroupBadges: View {
    let group: PhoneGroup
    var body: some View {
        HStack(spacing: 3) {
            ZStack(alignment: .topLeading) {
                ForEach(Array(group.members.prefix(3).enumerated()), id: \.element.ws) { index, member in
                    GroupMemberBadge(group: group, ws: member.ws, size: 28)
                        .offset(x: CGFloat(index * 16), y: CGFloat(index * 10))
                }
            }.frame(width: 60, height: 48)
            if group.members.count > 3 { Text("+\(group.members.count - 3)").themeFont(12) }
        }.accessibilityLabel(group.members.map { group.name(of: $0.ws) }.joined(separator: ", "))
    }
}

struct GroupListRow: View {
    static func rowID(_ group: PhoneGroup) -> String { "group-\(group.key.host.utf8.count)-\(group.key.host)-\(group.key.id)" }
    @Environment(AppModel.self) private var model
    let group: PhoneGroup
    var history = false
    var body: some View {
        TimelineView(.everyMinute) { context in
            let muted = model.notificationsMuted(workspace: group.messages.last(where: { !$0.message.fromPhone })?.message.message.from ?? group.key.host, group: group.key, now: context.date)
            NavigationLink(value: ChatRoute.group(host: group.key.host, id: group.key.id)) {
                HStack(spacing: 12) {
                    GroupBadges(group: group)
                    VStack(alignment: .leading, spacing: 5) {
                        HStack(spacing: 6) {
                            Text(group.title).themeFont(17, .semibold).foregroundStyle(history ? Theme.muted : Theme.text)
                            if muted { MutedIcon() }
                        }
                        Text(history
                             ? "finished \(ShellTime.day(group.messages.last?.at))"
                             : "\(group.members.count) helpers · started \(ShellTime.short(group.messages.first?.at))")
                            .themeFont(13).foregroundStyle(Theme.muted).lineLimit(1)
                    }.frame(maxWidth: .infinity, alignment: .leading)
                    VStack(spacing: 8) {
                        if !history { ShellBadge(count: model.readState.unread(GroupRoomRules.readKey(group), in: GroupRoomRules.readItems(group)), muted: muted) }
                    }
                }.padding(14).background(Theme.surface, in: RoundedRectangle(cornerRadius: Theme.Radius.m))
            }.buttonStyle(PressStyle()).foregroundStyle(Theme.text).accessibilityIdentifier(Self.rowID(group))
                .contextMenu {
                    MuteMenu(muted: model.isGroupMuted(group.key, now: context.date)) { mute in
                        Task { await model.setGroupMute(group.key, mute) }
                    }
                }
        }
    }

    private var lastLine: Text {
        guard let message = group.messages.last(where: { !$0.quiet && $0.event == nil && !$0.text.isEmpty }) else { return Text("Group started") }
        switch message.sender {
        case .host(let ws), .member(let ws), .person(let ws):
            return group.memberText(ws) + Text(": " + message.text)
        default: return Text(group.lastLine ?? "Group started")
        }
    }

}

struct GroupsSection: View {
    @Environment(AppModel.self) private var model
    var filter = "All"

    /// Open groups that pass the list filter (same rule as workspace rows).
    static func shown(_ model: AppModel, filter: String) -> [PhoneGroup] {
        let open = Set(ChatsRowRules.openQuestions(model.questions, answers: model.answers).map(\.id))
        return GroupRoomRules.rows(model.groups).filter { group in
            let unread = model.readState.unread(GroupRoomRules.readKey(group), in: GroupRoomRules.readItems(group))
            return ChatsRowRules.matches(filter, unread: unread, needsYou: GroupRoomRules.needsYou(group, open: open))
        }
    }

    /// Groups already filtered by the caller (the list computes them once per render).
    var groups: [PhoneGroup]

    var body: some View {
        if !groups.isEmpty {
            Text("Groups").themeFont(13, .semibold).foregroundStyle(Theme.muted).padding(.top, 12)
            ForEach(groups, id: \.key) { GroupListRow(group: $0) }
        }
        let finished = GroupRoomRules.rows(model.groups, closed: true).count
        // Helper-chat days stay reachable from each chat's "Earlier" button, so the row only appears with finished groups.
        if filter == "All" && finished > 0 {
            NavigationLink(value: ChatRoute.groupHistory) {
                HStack(spacing: 12) {
                    Image(systemName: "checkmark.circle").themeFont(20).foregroundStyle(Theme.muted).frame(width: 24).accessibilityHidden(true)
                    Text("Finished groups").themeFont(17, .semibold)
                    Spacer()
                    Text("\(finished)").themeFont(15).foregroundStyle(Theme.muted)
                    ShellChevron()
                }.frame(minHeight: 44).padding(.horizontal, 16).padding(.vertical, 12).contentShape(Rectangle())
                    .background(Theme.surface, in: RoundedRectangle(cornerRadius: Theme.Radius.m, style: .continuous))
            }.buttonStyle(PressStyle()).foregroundStyle(Theme.text).padding(.top, 6)
                .accessibilityIdentifier("group-history").accessibilityLabel("Finished groups").accessibilityValue("\(finished)")
        }
    }
}

struct GroupHistoryView: View {
    @Environment(AppModel.self) private var model
    var body: some View {
        ScrollView {
            VStack(spacing: 12) {
                Text("Earlier days").themeFont(15, .semibold).frame(maxWidth: .infinity, alignment: .leading)
                ForEach(model.workspaceSummaries) { summary in
                    ForEach(ChatDay.split(model.conversationItems(.general(workspace: summary.id)), today: ChatDay.key(for: Date())).past.reversed(), id: \.day) { day in
                        NavigationLink {
                            HistoryDayView(workspaceId: summary.id, day: day.day)
                        } label: {
                            Text("\(ChatDay.label(forDay: day.day, today: ChatDay.key(for: Date()))) · \(WorkspaceAlias.name(for: summary.workspace))")
                        }
                    }
                }
                Text("Finished groups").themeFont(15, .semibold).frame(maxWidth: .infinity, alignment: .leading)
                let groups = GroupRoomRules.rows(model.groups, closed: true)
                if groups.isEmpty { Text("No finished groups yet.").foregroundStyle(Theme.muted) }
                ForEach(groups, id: \.key) { GroupListRow(group: $0, history: true) }
            }.padding(16)
        }.background(Theme.bg).navigationTitle("Earlier").navigationBarTitleDisplayMode(.inline)
    }
}

/// A past General day pushed from Earlier: "Back to today" leaves it (like ChatHistoryView's dismiss).
private struct HistoryDayView: View {
    let workspaceId: String
    let day: String
    @Environment(\.dismiss) private var dismiss
    var body: some View {
        ConversationView(id: .general(workspace: workspaceId), historyDay: day, goToToday: { dismiss() })
    }
}

/// External identity never inherits the host's choice of icon or color.
struct GroupMemberBadge: View {
    let group: PhoneGroup
    let ws: String
    var size: CGFloat = 28
    var body: some View {
        let look = group.members.first { $0.ws == ws }?.look
        WorkspaceBadge(name: GroupRoomRules.badgeName(group: group, ws: ws),
                       icon: group.isExternal(ws) ? nil : look?.icon,
                       color: group.isExternal(ws) ? nil : look?.color, size: size, id: ws)
    }
}

extension PhoneGroup {
    func memberText(_ ws: String, prefix: String = "", suffix: String = "") -> Text {
        let text = Text(prefix + name(of: ws) + suffix)
        return isExternal(ws) ? text.italic().foregroundColor(Theme.muted) : text
    }
}
