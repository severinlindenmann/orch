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
            return (task.ws, ticket, local.key ?? "ticket", local.title)
        }
        if let local = updates.first(where: { $0.workspace == task.ws && $0.ticket == ticket }) {
            return (task.ws, ticket, local.key ?? "ticket", local.title)
        }
        return nil
    }

    static func taskHeading(target: (workspace: String, ticket: String, label: String, title: String?)?) -> String? {
        guard let target else { return nil }
        return [target.label, target.title].compactMap { $0 }.joined(separator: " · ")
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
        let formatter = ISO8601DateFormatter()
        for message in group.messages {
            let ws: String
            switch message.sender {
            case .host(let id), .member(let id): ws = id
            default: continue
            }
            guard group.members.contains(where: { $0.ws == ws }) else { continue }
            let kind = message.message.message.body.update?.kind
            if kind == "working" {
                formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
                let fractional = formatter.date(from: message.at)
                formatter.formatOptions = [.withInternetDateTime]
                working[ws] = fractional ?? formatter.date(from: message.at)
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

    static func readKey(_ group: PhoneGroup) -> String { "group:\(group.key.host)|\(group.key.id)" }
    static func readItems(_ group: PhoneGroup) -> [ChatItem] {
        group.messages.map { message in
            let incoming: Bool
            switch message.sender { case .you: incoming = false; default: incoming = true }
            return ChatItem(id: message.id, at: message.at, kind: incoming && !message.quiet ? .theirs(message.text, label: nil) : .mine(message.text, queued: false))
        }
    }

    static func eventText(_ event: GroupEvent, group: PhoneGroup, ownAnswer: String?) -> String {
        let name = group.name(of: event.ws ?? "")
        switch event.kind {
        case "created": return "Group started from ticket \(group.ticketKey ?? "") · \(group.title)"
        case "member_added": return "\(group.hostName) helper added \(name) to this group"
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
    var body: some View {
        NavigationLink(value: ChatRoute.group(host: group.key.host, id: group.key.id)) {
            HStack(spacing: 12) {
                GroupBadges(group: group)
                VStack(alignment: .leading, spacing: 5) {
                    Text(group.title).themeFont(17, .semibold)
                    lastLine.themeFont(13).foregroundStyle(Theme.muted).lineLimit(1)
                    KeyTag(key: group.ticketKey)
                }.frame(maxWidth: .infinity, alignment: .leading)
                VStack(spacing: 8) {
                    Text(ShellTime.short(group.messages.last?.at)).themeFont(12).foregroundStyle(Theme.muted)
                    ShellBadge(count: model.readState.unread(GroupRoomRules.readKey(group), in: GroupRoomRules.readItems(group)))
                }
            }.padding(14).background(Theme.surface, in: RoundedRectangle(cornerRadius: Theme.Radius.m))
        }.buttonStyle(PressStyle()).foregroundStyle(Theme.text).accessibilityIdentifier(Self.rowID(group))
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
    var body: some View {
        let groups = GroupRoomRules.rows(model.groups)
        if !groups.isEmpty {
            Text("Groups").themeFont(13, .semibold).foregroundStyle(Theme.muted).padding(.top, 12)
            ForEach(groups, id: \.key) { GroupListRow(group: $0) }
        }
        if !groups.isEmpty || !GroupRoomRules.rows(model.groups, closed: true).isEmpty {
            NavigationLink { GroupHistoryView() } label: {
                Text("Done groups › History").themeFont(15).foregroundStyle(Theme.brand).frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
            }.accessibilityIdentifier("group-history")
        }
    }
}

struct GroupHistoryView: View {
    @Environment(AppModel.self) private var model
    var body: some View {
        ScrollView {
            VStack(spacing: 12) {
                let groups = GroupRoomRules.rows(model.groups, closed: true)
                if groups.isEmpty { Text("No done groups yet.").foregroundStyle(Theme.muted) }
                ForEach(groups, id: \.key) { GroupListRow(group: $0) }
            }.padding(16)
        }.background(Theme.bg).navigationTitle("History").navigationBarTitleDisplayMode(.inline)
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
