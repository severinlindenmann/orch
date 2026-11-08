import SwiftUI

enum GroupRoomRules {
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

    static func readKey(_ group: PhoneGroup) -> String { "group:\(group.key.host)|\(group.id)" }
    static func readItems(_ group: PhoneGroup) -> [ChatItem] {
        group.messages.map { message in
            let incoming: Bool
            switch message.sender { case .you: incoming = false; default: incoming = true }
            return ChatItem(id: message.id, at: message.at, kind: incoming && !message.quiet ? .theirs(message.text, label: nil) : .mine(message.text, queued: false))
        }
    }

    static func eventText(_ event: GroupEvent, group: PhoneGroup) -> String {
        let name = group.name(of: event.ws ?? "")
        switch event.kind {
        case "created": return "Group started from ticket \(group.ticketKey ?? "") · \(group.title)"
        case "member_added": return "\(group.hostName) helper added \(name) to this group"
        case "member_left": return "\(event.name ?? name) left this group"
        case "approved": return "You allowed \(name) \(event.mode == "always" ? "always" : "once")"
        case "denied": return "You said no to \(name)"
        case "closed": return "This group is done"
        default: return ""
        }
    }
}

extension AppModel {
    /// Resolve again at send time: every text opts in using the newest host copy.
    @discardableResult
    func sendGroup(_ draft: MessageDraft, key: GroupKey) async throws -> OutboxItem {
        guard let group = groups.groups.first(where: { $0.key == key }),
              let ticket = group.ticket, let reply = GroupStore.replyTarget(in: group) else {
            throw SendRequest.Problem.badTarget
        }
        var draft = draft
        draft.replyTo = reply
        return try await send(draft, to: .topic(workspace: key.host, ticket: ticket))
    }
}

struct GroupBadges: View {
    let group: PhoneGroup
    var body: some View {
        HStack(spacing: 3) {
            ZStack(alignment: .topLeading) {
                ForEach(Array(group.members.prefix(3).enumerated()), id: \.element.ws) { index, member in
                    WorkspaceBadge(name: group.name(of: member.ws), icon: member.look?.icon, color: member.look?.color, size: 28, id: member.ws)
                        .offset(x: CGFloat(index * 16), y: CGFloat(index * 10))
                }
            }.frame(width: 60, height: 48)
            if group.members.count > 3 { Text("+\(group.members.count - 3)").themeFont(12) }
        }.accessibilityLabel(group.members.map { group.name(of: $0.ws) }.joined(separator: ", "))
    }
}

struct GroupListRow: View {
    @Environment(AppModel.self) private var model
    let group: PhoneGroup
    var body: some View {
        NavigationLink(value: ChatRoute.group(host: group.key.host, id: group.id)) {
            HStack(spacing: 12) {
                GroupBadges(group: group)
                VStack(alignment: .leading, spacing: 5) {
                    Text(group.title).themeFont(17, .semibold)
                    Text(group.lastLine ?? "Group started").themeFont(13).foregroundStyle(Theme.muted).lineLimit(1)
                    KeyTag(key: group.ticketKey)
                }.frame(maxWidth: .infinity, alignment: .leading)
                VStack(spacing: 8) {
                    Text(ShellTime.short(group.messages.last?.at)).themeFont(12).foregroundStyle(Theme.muted)
                    ShellBadge(count: model.readState.unread(GroupRoomRules.readKey(group), in: GroupRoomRules.readItems(group)))
                }
            }.padding(14).background(Theme.surface, in: RoundedRectangle(cornerRadius: Theme.Radius.m))
        }.buttonStyle(PressStyle()).foregroundStyle(Theme.text).accessibilityIdentifier("group-\(group.id)")
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
