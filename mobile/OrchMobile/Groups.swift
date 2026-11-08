import Foundation

struct GroupInfo: Codable, Sendable, Equatable {
    let id: String
    let host: String
    let title: String
    let members: [GroupMember]
    var seq: Int? = nil
}
struct GroupMember: Codable, Sendable, Equatable {
    let ws: String
    let name: String
    var look: GroupLook? = nil
}
struct GroupLook: Codable, Sendable, Equatable {
    var icon: String? = nil
    var color: String? = nil
}
struct GroupEvent: Codable, Sendable, Equatable {
    let kind: String
    var ws: String? = nil
    var name: String? = nil
    var look: GroupLook? = nil
    var fromSeq: Int? = nil
    var reason: String? = nil
    var delegate: String? = nil
    var questionMessage: String? = nil
    var mode: String? = nil
}
struct GroupOrigin: Codable, Sendable, Equatable {
    let id: String
    let from: String
    let at: String
}
struct GroupTask: Codable, Sendable, Equatable {
    let delegate: String
    let ws: String
    var ticket: String? = nil
    var key: String? = nil
    var title: String? = nil
    let status: String
    var questionMessage: String? = nil
}

struct GroupKey: Hashable, Sendable { let host: String; let id: String }
enum GroupSender: Equatable { case you, host(String), member(String), person(String) }
struct GroupMessage: Identifiable, Equatable {
    let id: String
    let at: String
    let seq: Int?
    let sender: GroupSender
    let text: String
    let event: GroupEvent?
    let task: GroupTask?
    let sharedFiles: [String]
    let ticketView: TicketSnapshot?
    let quiet: Bool
    let message: PhoneMessage
}
struct PhoneGroup: Identifiable, Equatable {
    let key: GroupKey
    var id: String { key.id }
    let title: String
    let members: [GroupMember]
    let hostName: String
    let names: [String: String]
    let ticketKey: String?
    let ticket: String?
    let messages: [GroupMessage]
    let closed: Bool
    let startedHere: Bool
    let gaps: [Int]
    let tasks: [String: GroupTask]

    func name(of ws: String) -> String { names[ws] ?? "Workspace" }

    var lastLine: String? {
        guard let last = messages.last(where: { !$0.quiet && $0.event == nil && !$0.text.isEmpty }) else { return nil }
        let name: String
        switch last.sender {
        case .you: name = "You"
        case .host(let ws), .member(let ws), .person(let ws):
            name = self.name(of: ws)
        }
        return "\(name): \(last.text)"
    }
}
struct GroupDrop: Equatable { let messageId: String; let rule: String; let reason: String }
struct GroupSnapshot: Equatable { let groups: [PhoneGroup]; let dropped: [GroupDrop] }
enum ApprovalCard: Equatable { case buttons(Question), answerInWorkspace(String), closed }

/// Phone receive rules only. Host-only delegate ownership and push-budget checks need host state we do not have.
enum GroupStore {
    private static let ranks = ["waiting_start": 0, "waiting_approval": 1, "queued": 2, "working": 3,
                                "done": 4, "failed": 4, "denied": 4]

    /// Nil means no receive-rule violation; messages without a group are ignored by `build`.
    /// state parameters must come from build()
    static func accept(_ m: PhoneMessage, workspaces: [String: String],
                       knownHosts: [String: String] = [:], tasks: [String: GroupTask] = [:],
                       closed: Bool = false) -> GroupDrop? {
        let msg = m.message, body = msg.body
        guard let group = body.group else { return nil }
        func drop(_ rule: String, _ reason: String) -> GroupDrop { GroupDrop(messageId: m.id, rule: rule, reason: reason) }
        guard msg.from.hasPrefix("ws_"), workspaces[msg.from] != nil else {
            return drop("G3", "Group sender is not a paired workspace")
        }
        if msg.from != group.host {
            return drop(body.by == "you" && body.groupEvent == nil ? "G4" : "G3", "Group sender is not its host")
        }
        guard let ticket = msg.ticket, group.id == "grp_" + ticket else {
            return drop("G1", "Group id does not match the host ticket")
        }
        if let host = knownHosts[group.id], host != group.host { return drop("G7", "Group id is already held under another host") }
        let members = Set(group.members.map(\.ws))
        guard group.members.count <= 8, members.count == group.members.count, members.contains(group.host),
              (1...120).contains(group.title.count) else { return drop("limit", "Invalid members or title") }
        if body.by == "you" {
            let dashboard = body.via == "dashboard" && body.origin?.from == "dashboard"
            let phone = body.via == "phone" && body.origin?.from.hasPrefix("ph_") == true && body.phone == body.origin?.from
            guard dashboard || phone else { return drop("G4", "Person attribution lacks a matching phone or dashboard origin") }
        } else if let by = body.by {
            guard by.hasPrefix("ws_"), members.contains(by), body.origin.map({ $0.from == by }) ?? true else {
                return drop("G4", "Workspace attribution does not match membership or origin")
            }
        }
        if let event = body.groupEvent, event.kind == "member_added",
           event.ws == nil || event.name == nil || event.fromSeq == nil {
            return drop("G3", "Member-added event lacks ws, name or from_seq")
        }
        if let task = body.task {
            guard members.contains(task.ws), let rank = ranks[task.status] else { return drop("G9", "Unknown task member or status") }
            if let by = body.by, by != group.host {
                if task.status == "waiting_start" { return drop("G6", "Only the host may report waiting_start") }
                if members.contains(by), task.ws != by { return drop("G6", "Member may only report its own task") }
            }
            if let previous = tasks[task.delegate], let priorRank = ranks[previous.status],
               rank < priorRank || (priorRank == 4 && task.status != previous.status) {
                return drop("G9", "Task status went backwards or left a final state")
            }
        }
        // shared_files contains blob ids, not Attachment.id (which is a UI identity).
        let blobs = Set(body.ticketView?.attachments.compactMap(\.blobId) ?? [])
        guard Set(body.sharedFiles ?? []).isSubset(of: blobs) else { return drop("G5", "Shared file is absent from ticket_view attachments") }
        if closed && body.groupEvent?.kind != "closed" { return drop("closed", "Group is closed") }
        return nil
    }

    static func build(messages: [PhoneMessage], workspaces: [String: String],
                      ownPhoneId: String, ownMessageIds: Set<String>) -> GroupSnapshot {
        var held: [GroupKey: [GroupMessage]] = [:], hosts: [String: String] = [:]
        var tasks: [GroupKey: [String: GroupTask]] = [:]
        var closed = Set<GroupKey>(), ids = Set<String>(), origins: [GroupKey: Set<String>] = [:]
        var dropped: [GroupDrop] = [], keys: [GroupKey] = []
        // The input is newest first. Reverse preserves first delivery for equal timestamps.
        for m in messages.reversed() {
            let body = m.message.body
            guard let info = body.group else { continue }
            let key = GroupKey(host: info.host, id: info.id)
            guard !ids.contains(m.id), body.origin.map({ !(origins[key] ?? []).contains($0.id) }) ?? true else { continue }
            if let drop = accept(m, workspaces: workspaces, knownHosts: hosts, tasks: tasks[key] ?? [:], closed: closed.contains(key)) {
                dropped.append(drop); continue
            }
            ids.insert(m.id)
            if let origin = body.origin { origins[key, default: []].insert(origin.id) }
            hosts[info.id] = info.host
            if let task = body.task { tasks[key, default: [:]][task.delegate] = task }
            if body.groupEvent?.kind == "closed" { closed.insert(key) }
            if let echo = body.echoOf, ownMessageIds.contains(echo), body.phone == ownPhoneId { continue }
            if held[key] == nil { keys.append(key) }
            let sender: GroupSender
            if body.by == "you" { sender = .you }
            else if let by = body.by, by != info.host { sender = .member(by) }
            else { sender = .host(info.host) }
            held[key, default: []].append(GroupMessage(id: m.id, at: m.message.createdAt, seq: info.seq, sender: sender,
                text: body.text, event: body.groupEvent, task: body.task, sharedFiles: body.sharedFiles ?? [], ticketView: body.ticketView,
                quiet: ["ack", "working", "note"].contains(body.update?.kind ?? ""), message: m))
        }
        let groups = keys.compactMap { key -> PhoneGroup? in
            guard let heldMessages = held[key], let newest = heldMessages.max(by: {
                ($0.seq ?? Int.min, $0.at, $0.id) < ($1.seq ?? Int.min, $1.at, $1.id)
            }), let info = newest.message.message.body.group else { return nil }
            let ordered = order(heldMessages)
            let seqs = Set(ordered.compactMap(\.seq)).sorted()
            var gaps: [Int] = []
            for (low, high) in zip(seqs, seqs.dropFirst()) where low < high - 1 {
                gaps.append(contentsOf: (low + 1)..<high)
            }
            let names = Dictionary(uniqueKeysWithValues: info.members.map { member in
                let name = (workspaces[member.ws] ?? member.name).trimmingCharacters(in: .whitespacesAndNewlines)
                return (member.ws, name.isEmpty || name.lowercased() == "you" ? "Workspace" : name)
            })
            return PhoneGroup(key: key, title: info.title, members: info.members, hostName: workspaces[key.host] ?? key.host, names: names,
                ticketKey: newest.message.message.key, ticket: newest.message.message.ticket, messages: ordered,
                closed: closed.contains(key), startedHere: heldMessages.contains { $0.event?.kind == "created" },
                gaps: gaps, tasks: tasks[key] ?? [:])
        }
        return GroupSnapshot(groups: groups, dropped: dropped)
    }

    private static func order(_ messages: [GroupMessage]) -> [GroupMessage] {
        let sequenced = messages.filter { $0.seq != nil }.sorted {
            ($0.seq ?? 0, $0.at, $0.id) < ($1.seq ?? 0, $1.at, $1.id)
        }
        var slots: [Int: [GroupMessage]] = [:]
        for m in messages.filter({ $0.seq == nil }).sorted(by: { ($0.at, $0.id) < ($1.at, $1.id) }) {
            let slot = sequenced.lastIndex { $0.at <= m.at }.map { $0 + 1 } ?? 0
            slots[slot, default: []].append(m)
        }
        var result = slots[0] ?? []
        for (index, m) in sequenced.enumerated() { result.append(m); result.append(contentsOf: slots[index + 1] ?? []) }
        return result
    }

    static func replyTarget(in group: PhoneGroup) -> String? {
        guard !group.closed else { return nil }
        return group.messages.last { $0.message.message.from == group.key.host && $0.message.message.to == "phones" }?.id
    }

    static func approvalCard(for event: GroupEvent, in group: PhoneGroup, questions: [Question]) -> ApprovalCard {
        if event.kind == "approval_needed", let ws = event.ws, group.members.contains(where: { $0.ws == ws }),
           let q = questions.first(where: {
               $0.id == event.questionMessage && $0.message.from == ws && $0.isAllow &&
               $0.message.body.scope?.trimmingCharacters(in: .whitespacesAndNewlines)
                   .caseInsensitiveCompare("tasks from \(group.hostName)") == .orderedSame
           }) {
            return .buttons(q)
        }
        return .answerInWorkspace(group.name(of: event.ws ?? ""))
    }
}
