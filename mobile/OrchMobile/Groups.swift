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
    var mode: String? = nil // approved: once|always (allow messages use once|permanent)
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
enum GroupSender: Equatable { case you, otherPhone, host(String), member(String), person(String) }
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
    var late: Bool = false
}
struct PhoneGroup: Identifiable, Equatable {
    let key: GroupKey
    var id: GroupKey { key }
    let title: String
    let members: [GroupMember]
    let hostName: String
    let names: [String: String]
    let ticketKey: String?
    let ticket: String?
    let messages: [GroupMessage]
    let closed: Bool
    let startedHere: Bool
    let gaps: [Range<Int>]
    var hasGaps: Bool { !gaps.isEmpty }
    let tasks: [String: GroupTask]
    var appliedSeq: Int? = nil

    func name(of ws: String) -> String { names[ws] ?? "Workspace" }

    var lastLine: String? {
        guard let last = messages.last(where: { !$0.quiet && $0.event == nil && !$0.text.isEmpty }) else { return nil }
        let name: String
        switch last.sender {
        case .you: name = "You"
        case .otherPhone: name = "Other phone"
        case .host(let ws), .member(let ws), .person(let ws):
            name = self.name(of: ws)
        }
        return "\(name): \(last.text)"
    }
}
struct GroupDrop: Equatable { let messageId: String; let rule: String; let reason: String }
struct GroupSnapshot: Equatable { let groups: [PhoneGroup]; let dropped: [GroupDrop] }
enum ApprovalCard: Equatable { case buttons(Question), answerInWorkspace(String), closed }

/// Receive-order state, independent of transcript display order.
struct GroupOrder {
    enum Outcome: String { case apply, buffer, skipJumpAndApply = "skip_jump_and_apply", skipGapAndApply = "skip_gap_and_apply", lateShowNoState = "late_show_no_state" }
    var appliedSeq: Int?
    var buffered: [Int: Date] = [:]
    private(set) var released: [Int] = []
    private(set) var superseded: [Int] = []
    private(set) var gaps: [Range<Int>] = []

    init(appliedSeq: Int? = nil, fromSeq: Int? = nil, buffered: [Int: Date] = [:]) {
        // from_seq is display information; only the first received seq seeds state.
        self.appliedSeq = appliedSeq
        self.buffered = buffered
    }

    mutating func receive(seq: Int, receivedAt: Date, now: Date) -> Outcome {
        released = []
        superseded = []
        // Defense in depth for direct callers as well as cached host messages.
        guard (1...Int(Int32.max)).contains(seq) else { return .lateShowNoState }
        if appliedSeq == nil { appliedSeq = seq - 1 }
        guard seq > appliedSeq! else { return .lateShowNoState }
        let (distance, overflow) = seq.subtractingReportingOverflow(appliedSeq!)
        if overflow || distance > 1000 {
            if appliedSeq! < seq - 1 { recordGap((appliedSeq! + 1)..<seq) }
            appliedSeq = seq - 1
            superseded = buffered.keys.filter { $0 <= appliedSeq! }.sorted()
            for old in superseded { buffered.removeValue(forKey: old) }
            buffered[seq] = buffered[seq] ?? receivedAt
            drain()
            #if DEBUG
            print("GroupOrder: seq jump > 1000; skip gap and apply \(seq)")
            #endif
            return .skipJumpAndApply
        }
        buffered[seq] = buffered[seq] ?? receivedAt
        drain()
        let skipped = skipExpired(now: max(now, receivedAt))
        return skipped ? .skipGapAndApply : released.isEmpty ? .buffer : .apply
    }

    /// Also called when rebuilding a quiet group with no newly arrived message.
    mutating func flush(now: Date) {
        released = []
        superseded = []
        _ = skipExpired(now: now)
    }

    private mutating func drain() {
        while let applied = appliedSeq {
            let (next, overflow) = applied.addingReportingOverflow(1)
            guard !overflow, buffered.removeValue(forKey: next) != nil else { break }
            appliedSeq = next
            released.append(next)
        }
    }

    private mutating func recordGap(_ range: Range<Int>) {
        var merged: [Range<Int>] = []
        for next in (gaps + [range]).sorted(by: { $0.lowerBound < $1.lowerBound }) {
            if let last = merged.last, next.lowerBound <= last.upperBound {
                merged[merged.count - 1] = last.lowerBound..<max(last.upperBound, next.upperBound)
            } else {
                merged.append(next)
            }
        }
        // Gaps advance in sequence order, so the lowest ranges are the oldest.
        gaps = Array(merged.suffix(50))
    }

    private mutating func skipExpired(now: Date) -> Bool {
        var skipped = false
        while let oldest = buffered.values.min(), let lowest = buffered.keys.min() {
            guard buffered.count > 50 || now.timeIntervalSince(oldest) >= 600 else { break }
            if let applied = appliedSeq {
                let (next, overflow) = applied.addingReportingOverflow(1)
                if !overflow, lowest > next { recordGap(next..<lowest) }
                // Discard stale entries supplied by direct callers without regressing state.
                if lowest <= applied {
                    buffered.removeValue(forKey: lowest)
                    continue
                }
            }
            buffered.removeValue(forKey: lowest)
            appliedSeq = lowest
            released.append(lowest)
            drain()
            skipped = true
        }
        return skipped
    }
}

struct GroupCaps {
    static func accepts(openGroups: Int, createdLastHour: Int) -> Bool {
        openGroups < 20 && createdLastHour < 5
    }
}

/// Phone receive rules only. Host-only delegate ownership and push-budget checks need host state we do not have.
enum GroupStore {
    private static let ranks = ["waiting_start": 0, "waiting_approval": 1, "queued": 2, "working": 3,
                                "done": 4, "failed": 4, "denied": 4]

    /// Nil means no receive-rule violation; messages without a group are ignored by `build`.
    /// state parameters must come from build()
    static func accept(_ m: PhoneMessage, workspaces: [String: String],
                       tasks: [String: GroupTask] = [:],
                       closed: Bool = false) -> GroupDrop? {
        let msg = m.message, body = msg.body
        guard let group = body.group else { return nil }
        func drop(_ rule: String, _ reason: String) -> GroupDrop { GroupDrop(messageId: m.id, rule: rule, reason: reason) }
        if [group.seq, body.groupEvent?.fromSeq].contains(where: {
            $0.map { !(1...Int(Int32.max)).contains($0) } ?? false
        }) {
            return drop("G12", "seq out of range")
        }
        guard msg.from.hasPrefix("ws_"), workspaces[msg.from] != nil else {
            return drop("G3", "Group sender is not a paired workspace")
        }
        if msg.from != group.host {
            return drop("G3", "Group sender is not its host")
        }
        guard let ticket = msg.ticket, group.id == "grp_" + ticket else {
            return drop("G1", "Group id does not match the host ticket")
        }
        let members = Set(group.members.map(\.ws))
        guard group.members.count <= 8, members.count == group.members.count, members.contains(group.host),
              (1...120).contains(group.title.count) else { return drop("limit", "Invalid members or title") }
        if body.by == "you" {
            let dashboard = body.via == "dashboard" && body.origin?.from == "dashboard" && body.phone == nil
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
        if let event = body.groupEvent, event.kind == "approved", !["once", "always"].contains(event.mode ?? "") {
            return drop("G11", "Approved mode must be once or always")
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
                      ownPhoneId: String, ownMessageIds: Set<String>, receivedAt: [String: Date] = [:], arrival: [String: Int] = [:], now: Date = Date()) -> GroupSnapshot {
        var held: [GroupKey: [GroupMessage]] = [:]
        var tasks: [GroupKey: [String: GroupTask]] = [:]
        var closed = Set<GroupKey>(), ids: [GroupKey: Set<String>] = [:], origins: [GroupKey: Set<String>] = [:]
        var dropped: [GroupDrop] = [], keys: [GroupKey] = []
        var orders: [GroupKey: GroupOrder] = [:], pending: [GroupKey: [Int: PhoneMessage]] = [:]
        var latest: [GroupKey: PhoneMessage] = [:]
        var creations: [String: [Date]] = [:]
        var clocks: [GroupKey: Date] = [:]
        func apply(_ m: PhoneMessage, key: GroupKey, late: Bool = false) {
            let body = m.message.body, info = body.group!
            if !late {
                if let drop = accept(m, workspaces: workspaces, tasks: tasks[key] ?? [:], closed: closed.contains(key)) {
                    dropped.append(drop); return
                }
                latest[key] = m
                if let task = body.task { tasks[key, default: [:]][task.delegate] = task }
                if body.groupEvent?.kind == "closed" { closed.insert(key) }
            }
            if let echo = body.echoOf, ownMessageIds.contains(echo), body.phone == ownPhoneId { return }
            let sender: GroupSender
            if body.by == "you" {
                sender = body.origin?.from == ownPhoneId || body.origin?.from == "dashboard" ? .you : .otherPhone
            } else if let by = body.by, by != info.host { sender = .member(by) }
            else { sender = .host(info.host) }
            held[key, default: []].append(GroupMessage(id: m.id, at: m.message.createdAt, seq: info.seq, sender: sender,
                text: body.text, event: body.groupEvent, task: body.task, sharedFiles: body.sharedFiles ?? [], ticketView: body.ticketView,
                quiet: ["ack", "working", "note"].contains(body.update?.kind ?? ""), message: m, late: late))
        }
        func release(_ key: GroupKey) {
            for seq in orders[key]?.superseded ?? [] {
                if let m = pending[key]?.removeValue(forKey: seq) { apply(m, key: key, late: true) }
            }
            for seq in orders[key]?.released ?? [] {
                if let m = pending[key]?.removeValue(forKey: seq) { apply(m, key: key) }
            }
        }
        // Explicit relay arrival order survives display sorting. Missing entries use reversed array order.
        let incoming = messages.reversed().enumerated().sorted {
            let a = arrival[$0.element.id] ?? $0.offset, b = arrival[$1.element.id] ?? $1.offset
            return a == b ? $0.offset < $1.offset : a < b
        }.map(\.element)
        for m in incoming {
            let body = m.message.body
            guard let info = body.group else { continue }
            let key = GroupKey(host: info.host, id: info.id)
            if info.seq == nil {
                if let drop = accept(m, workspaces: workspaces) { dropped.append(drop); continue }
                guard orders[key] != nil else {
                    dropped.append(GroupDrop(messageId: m.id, rule: "G12", reason: "group message without seq"))
                    continue
                }
                apply(m, key: key, late: true)
                continue
            }
            if ids[key]?.contains(m.id) == true { continue }
            if let origin = body.origin, origins[key]?.contains(origin.id) == true {
                dropped.append(GroupDrop(messageId: m.id, rule: "G7", reason: "Duplicate group origin")); continue
            }
            if let drop = accept(m, workspaces: workspaces) { dropped.append(drop); continue }
            let time = receivedAt[m.id] ?? now
            if orders[key] == nil {
                let recent = (creations[key.host] ?? []).filter { $0 > time.addingTimeInterval(-3600) && $0 <= time }
                let open = keys.filter { $0.host == key.host && !closed.contains($0) }.count
                guard GroupCaps.accepts(openGroups: open, createdLastHour: recent.count) else {
                    dropped.append(GroupDrop(messageId: m.id, rule: "cap", reason: "Host group creation cap exceeded")); continue
                }
                creations[key.host, default: []].append(time)
                keys.append(key)
                orders[key] = GroupOrder()
                latest[key] = m
            }
            ids[key, default: []].insert(m.id)
            if let origin = body.origin { origins[key, default: []].insert(origin.id) }
            if let seq = info.seq {
                let clock = max(clocks[key] ?? time, time)
                let outcome = orders[key]!.receive(seq: seq, receivedAt: time, now: clock)
                if outcome == .lateShowNoState { apply(m, key: key, late: true) }
                else {
                    clocks[key] = clock
                    // A repeated buffered seq cannot replace its original payload.
                    if pending[key]?[seq] == nil { pending[key, default: [:]][seq] = m }
                    release(key)
                }
            }
        }
        for key in keys {
            orders[key]!.flush(now: now)
            release(key)
        }
        let groups = keys.compactMap { key -> PhoneGroup? in
            guard let heldMessages = held[key], !heldMessages.isEmpty,
                  let newest = latest[key], let info = newest.message.body.group else { return nil }
            let names = Dictionary(uniqueKeysWithValues: info.members.map { member in
                let name = (workspaces[member.ws] ?? member.name).trimmingCharacters(in: .whitespacesAndNewlines)
                let normalized = String(String.UnicodeScalarView(name.precomposedStringWithCompatibilityMapping
                    .unicodeScalars.filter { $0.properties.generalCategory != .format }))
                    .trimmingCharacters(in: .whitespacesAndNewlines)
                    .folding(options: .caseInsensitive, locale: Locale(identifier: "en_US_POSIX"))
                return (member.ws, ["", "you", "other phone"].contains(normalized) ? "Workspace" : name)
            })
            return PhoneGroup(key: key, title: info.title, members: info.members, hostName: workspaces[key.host] ?? key.host, names: names,
                ticketKey: newest.message.key, ticket: newest.message.ticket, messages: order(heldMessages),
                closed: closed.contains(key), startedHere: heldMessages.contains { !$0.late && $0.event?.kind == "created" },
                gaps: orders[key]?.gaps ?? [], tasks: tasks[key] ?? [:], appliedSeq: orders[key]?.appliedSeq)
        }
        return GroupSnapshot(groups: groups, dropped: dropped)
    }

    static func applyOrder(_ messages: [PhoneMessage]) -> [PhoneMessage] {
        ordered(messages) { ($0.message.body.group?.seq, $0.message.createdAt, $0.id) }
    }

    private static func order(_ messages: [GroupMessage]) -> [GroupMessage] {
        ordered(messages) { ($0.seq, $0.at, $0.id) }
    }

    private static func ordered<T>(_ messages: [T], fields: (T) -> (seq: Int?, at: String, id: String)) -> [T] {
        let sequenced = messages.filter { fields($0).seq != nil }.sorted {
            let a = fields($0), b = fields($1)
            return (a.seq ?? 0, a.id) < (b.seq ?? 0, b.id)
        }
        var slots: [Int: [T]] = [:]
        for m in messages.filter({ fields($0).seq == nil }).sorted(by: {
            let a = fields($0), b = fields($1)
            return (a.at, a.id) < (b.at, b.id)
        }) {
            let slot = sequenced.lastIndex { fields($0).at <= fields(m).at }.map { $0 + 1 } ?? 0
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

    static func approvalCard(for event: GroupEvent, in group: PhoneGroup, questions: [Question], late: Bool = false) -> ApprovalCard {
        guard !group.closed, !late else { return .closed }
        if event.kind == "approval_needed", let ws = event.ws, group.members.contains(where: { $0.ws == ws }),
           let q = questions.first(where: {
               $0.id == event.questionMessage && $0.message.from == ws && $0.isGroupAllow &&
               $0.message.body.scope?.trimmingCharacters(in: .whitespacesAndNewlines)
                   .caseInsensitiveCompare("tasks from \(group.hostName)") == .orderedSame
           }) {
            return .buttons(q)
        }
        return .answerInWorkspace(group.name(of: event.ws ?? ""))
    }
}
