import SwiftUI

/// Pieces shared by the chat screens: avatar, bubbles, cards, composer. Original messenger look in the orch dark theme.

struct Avatar: View {
    let name: String
    var size: CGFloat = 40
    var body: some View {
        Text(String(name.prefix(1)).uppercased()).themeFont(size * 0.42, .semibold).foregroundStyle(Theme.brand)
            .frame(width: size, height: size).background(Theme.brand.opacity(0.14), in: RoundedRectangle(cornerRadius: size * 0.3))
            .overlay(RoundedRectangle(cornerRadius: size * 0.3).stroke(Theme.brand.opacity(0.35)))
            .accessibilityHidden(true)
    }
}

struct KeyTag: View {
    let key: String?
    @ScaledMetric(relativeTo: .caption) private var size: CGFloat = 12
    var body: some View {
        if let key { Text(key).font(.system(size: size, design: .monospaced)).foregroundStyle(Theme.muted) }
    }
}

struct StatusPill: View {
    let status: Ticket.Status
    let kind: String
    var text: String {
        switch status { case .needsYou: "Needs you"; case .working: "Working"; case .done: kind == "result" ? "Done" : (kind == "stopped" ? "Stopped" : "Did not work") }
    }
    var color: Color { switch status { case .needsYou: Theme.warn; case .working: Theme.brand; case .done: kind == "result" ? Theme.muted : Theme.danger } }
    var body: some View {
        Text(text).themeFont(11, .semibold).foregroundStyle(color).padding(.horizontal, 8).padding(.vertical, 3)
            .overlay(Capsule().stroke(color.opacity(0.6)))
    }
}

struct UnreadBadge: View {
    let count: Int
    var body: some View {
        if count > 0 {
            Text("\(count)").themeFont(12, .bold).foregroundStyle(Theme.onBrand).padding(.horizontal, 7).frame(minWidth: 22, minHeight: 22)
                .background(Theme.brand, in: Capsule()).accessibilityLabel("\(count) unread")
        }
    }
}

struct TextBubble: View {
    let text: String
    var mine = false
    var queued = false
    var label: String? = nil
    var sender: String? = nil
    var at: String = ""
    var body: some View {
        HStack {
            if mine { Spacer(minLength: 48) }
            VStack(alignment: .leading, spacing: 4) {
                if let sender { Text(sender).themeFont(11, .semibold).foregroundStyle(Theme.brand) }
                if let label { Eyebrow(text: label, color: Theme.brand) }
                Text(text).themeFont(16).fixedSize(horizontal: false, vertical: true)
                HStack(spacing: 6) {
                    Spacer(minLength: 0)
                    if queued { Image(systemName: "clock").accessibilityHidden(true); Text("Waiting to send") }
                    Text(ChatBuilder.timeText(at))
                }.themeFont(11).foregroundStyle(Theme.muted)
            }.padding(.horizontal, 12).padding(.vertical, 9)
                .background(mine ? Theme.brand.opacity(0.14) : Theme.surface2, in: RoundedRectangle(cornerRadius: 14))
                .overlay(RoundedRectangle(cornerRadius: 14).stroke(mine ? Theme.brand.opacity(0.5) : Theme.border))
            if !mine { Spacer(minLength: 48) }
        }.accessibilityElement(children: .combine)
    }
}

struct SystemLine: View {
    let text: String
    var body: some View {
        Text(text).themeFont(12).foregroundStyle(Theme.muted).padding(.horizontal, 12).padding(.vertical, 6)
            .overlay(Capsule().stroke(Theme.border)).frame(maxWidth: .infinity).multilineTextAlignment(.center)
    }
}

/// Ticket card in the workspace chat: key, title, tasks progress, "Open chat".
struct TicketCardBubble: View {
    let ticket: Ticket
    var body: some View {
        NavigationLink(value: ChatRoute.ticket(workspace: ticket.workspace, ticket: ticket.ticket ?? "")) {
            VStack(alignment: .leading, spacing: 8) {
                HStack { Text("TICKET").themeFont(11, .semibold).tracking(1).foregroundStyle(Theme.muted); KeyTag(key: ticket.key); Spacer(); StatusPill(status: ticket.status, kind: ticket.kind) }
                Text(ticket.displayTitle).themeFont(16, .semibold).multilineTextAlignment(.leading)
                if let v = ticket.view, v.totalCount > 0 {
                    Text("\(v.doneCount) of \(v.totalCount) tasks").themeFont(12).foregroundStyle(Theme.muted)
                    ProgressBar(done: v.doneCount, total: v.totalCount)
                }
                HStack { Text("Open chat").foregroundStyle(Theme.brand); Spacer(); Image(systemName: "chevron.right").foregroundStyle(Theme.brand) }.themeFont(13, .semibold)
            }.orchCard(padding: 12).foregroundStyle(Theme.text)
        }.buttonStyle(PressStyle()).accessibilityIdentifier("card-\(ticket.id)")
    }
}

struct ProgressBar: View {
    let done: Int, total: Int
    var body: some View {
        GeometryReader { g in
            ZStack(alignment: .leading) {
                Capsule().fill(Theme.surface3)
                Capsule().fill(Theme.brand).frame(width: g.size.width * CGFloat(done) / CGFloat(max(total, 1)))
            }
        }.frame(height: 4).accessibilityHidden(true)
    }
}

/// A question as a bubble: options (or Allow once / Always / Ignore), then a 5 s undo, then the answer.
struct QuestionBubble: View {
    @Environment(AppModel.self) private var model
    let question: Question
    @Environment(\.dynamicTypeSize) private var typeSize

    var body: some View {
        let q = question
        let answer = model.answers[q.id]
        let accent = q.isAllow ? Theme.warn : Theme.warn
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 6) {
                Image(systemName: q.isAllow ? "lock.fill" : "exclamationmark.circle").accessibilityHidden(true)
                Text(answer != nil ? "Answered" : (q.isAllow ? "Permission" : "Needs you")).themeFont(12, .semibold)
            }.foregroundStyle(answer != nil ? Theme.muted : accent)
            Text(q.message.body.text).themeFont(17, .semibold).fixedSize(horizontal: false, vertical: true)
            if q.message.key != nil || q.message.body.title != nil {
                HStack(spacing: 6) { KeyTag(key: q.message.key); if let t = q.message.body.title { Text(t).themeFont(12).foregroundStyle(Theme.muted) } }
            }
            if let answer {
                Text(model.answeredElsewhere.contains(q.id) ? "Already answered: \(answer)" : "✓ \(q.label(answer)) · answered from this phone")
                    .themeFont(14).foregroundStyle(Theme.brand).accessibilityIdentifier("answered-\(q.id)")
            } else if let choice = model.pendingAnswers[q.id] {
                HStack(spacing: 10) {
                    ProgressView().tint(Theme.brand)
                    Text(model.sendingAnswers.contains(q.id) ? "Sending \(q.label(choice))…" : "Sending \(q.label(choice)) in a moment…").themeFont(14, .medium)
                    Spacer()
                    if !model.sendingAnswers.contains(q.id) {
                        Button("Undo") { model.undoAnswer(q) }.themeFont(14, .semibold).foregroundStyle(Theme.brand)
                            .frame(minWidth: 60, minHeight: 44).accessibilityIdentifier("undo-\(q.id)")
                    }
                }
            } else {
                let layout = q.isAllow ? AnyLayout(HStackLayout(spacing: 8)) : AnyLayout(VStackLayout(spacing: 8))
                layout {
                    ForEach(q.message.body.options, id: \.self) { option in optionButton(q, option) }
                }
            }
        }.padding(14).frame(maxWidth: .infinity, alignment: .leading)
            .background(Theme.surface, in: RoundedRectangle(cornerRadius: 14))
            .overlay(alignment: .leading) { if answer == nil { Rectangle().fill(accent).frame(width: 3).clipShape(RoundedRectangle(cornerRadius: 2)) } }
            .overlay(RoundedRectangle(cornerRadius: 14).stroke(model.focusedQuestion == q.id ? Theme.brand : Theme.border))
            .accessibilityElement(children: .contain).accessibilityIdentifier("question-\(q.id)")
    }

    @ViewBuilder private func optionButton(_ q: Question, _ option: String) -> some View {
        let recommended = option == q.message.body.recommended
        let primary = q.isAllow && option == "Once"
        Button { model.chooseAnswer(q, option) } label: {
            HStack(spacing: 8) {
                Text(q.label(option)).themeFont(15, primary ? .semibold : .regular).lineLimit(3)
                if !q.isAllow { Spacer(minLength: 0) }
                if recommended { Text("Suggested").themeFont(11, .semibold).foregroundStyle(Theme.brand).fixedSize() }
            }.frame(maxWidth: q.isAllow ? nil : .infinity, minHeight: 46, alignment: .leading).padding(.horizontal, 14)
                .foregroundStyle(primary ? Theme.onBrand : Theme.text)
                .background(primary ? Theme.brand : Theme.surface2, in: RoundedRectangle(cornerRadius: q.isAllow ? 20 : 10))
                .overlay(RoundedRectangle(cornerRadius: q.isAllow ? 20 : 10).stroke(primary ? Color.clear : Theme.borderStrong))
                .contentShape(Rectangle())
        }.buttonStyle(PressStyle()).accessibilityIdentifier("answer-\(option)")
            .accessibilityLabel(recommended ? "\(q.label(option)), suggested" : q.label(option))
    }
}

struct AttachmentBubble: View {
    let attachment: TicketSnapshot.Attachment
    var at: String = ""
    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 6) {
                Text("Agent").themeFont(11, .semibold).foregroundStyle(Theme.brand)
                AttachmentTile(attachment: attachment, large: true)
                Text(ChatBuilder.timeText(at)).themeFont(11).foregroundStyle(Theme.muted).frame(maxWidth: .infinity, alignment: .trailing)
            }.padding(10).background(Theme.surface2, in: RoundedRectangle(cornerRadius: 14))
                .overlay(RoundedRectangle(cornerRadius: 14).stroke(Theme.border))
            Spacer(minLength: 48)
        }.accessibilityIdentifier("attachment-\(attachment.kind)")
    }
}

/// Image (only from the relay blob, never from an arbitrary address), link or file.
struct AttachmentTile: View {
    let attachment: TicketSnapshot.Attachment
    var large = false
    var body: some View {
        switch attachment.kind {
        case "image":
            if let id = attachment.blobId, BlobID.isValid(id) {
                VStack(alignment: .leading, spacing: 6) {
                    BlobImage(id: id).frame(maxWidth: .infinity).frame(height: large ? 140 : 84).clipShape(RoundedRectangle(cornerRadius: 8))
                    Text(attachment.label ?? "Image").themeFont(12).foregroundStyle(Theme.text).lineLimit(1)
                }
            } else {
                // A picture that only has an address is a link card: nothing loads until the person taps it.
                row(symbol: "photo", title: attachment.label ?? "Image", sub: SafeLink.host(attachment.url) ?? "")
            }
        case "link":
            linkCard
        default:
            row(symbol: "doc", title: attachment.label ?? "File", sub: attachment.size.map { ByteCountFormatter.string(fromByteCount: Int64($0), countStyle: .file) } ?? "")
        }
    }
    /// A link card: the site or link-type tile (GH, Fg …), title, what it is, and the add-on's status.
    private var linkCard: some View {
        let a = attachment, host = SafeLink.host(a.url) ?? ""
        let inner = HStack(spacing: 10) {
            LinkTile(icon: LinkFace.icon(a.icon, url: a.url), mono: a.mono)
            VStack(alignment: .leading, spacing: 2) {
                Text(LinkFace.oneLine(a.title, max: 200) ?? host).themeFont(14, .semibold).lineLimit(1)
                HStack(spacing: 0) {  // the host never truncates: the type gives way first
                    if let t = LinkFace.type(a.linkType) { Text(t + " · ").lineLimit(1).truncationMode(.tail) }
                    Text(LinkFace.host(a.url)).lineLimit(1).fixedSize().layoutPriority(1)
                }.themeFont(12).foregroundStyle(Theme.muted)
            }
            Spacer(minLength: 0)
            if let s = a.status, !s.isEmpty { LinkStatus(text: s) }
        }.foregroundStyle(Theme.text)
        return Group { if let u = SafeLink.url(a.url) { Link(destination: u) { inner } } else { inner } }
            .accessibilityIdentifier("link-card")
    }
    private func row(symbol: String, title: String, sub: String) -> some View {
        let inner = HStack(spacing: 10) {
            Image(systemName: symbol).foregroundStyle(Theme.brand).frame(width: 34, height: 34).background(Theme.surface3, in: RoundedRectangle(cornerRadius: 8))
            VStack(alignment: .leading, spacing: 2) { Text(title).themeFont(14, .semibold).lineLimit(1); Text(sub).themeFont(12).foregroundStyle(Theme.muted).lineLimit(1) }
            Spacer(minLength: 0)
        }.foregroundStyle(Theme.text)
        return Group {
            if attachment.kind != "file", let u = SafeLink.url(attachment.url) { Link(destination: u) { inner } } else { inner }
        }
    }
}

/// Loads an image through the relay (paired credentials); a failure or a non-image shows a plain placeholder.
struct BlobImage: View {
    @Environment(AppModel.self) private var model
    let id: String
    @State private var image: UIImage?
    var body: some View {
        ZStack {
            Theme.surface3
            if let image { Image(uiImage: image).resizable().scaledToFill() }
            else { Image(systemName: "photo").font(.system(size: 28)).foregroundStyle(Theme.muted) }
        }.clipped().task(id: id) {
            if let d = await model.blob(id) { image = Thumbnail.image(from: d) }
        }
    }
}

/// Text field + send. The note under it says what happens to the text.
struct Composer: View {
    let placeholder: String
    let note: String
    var onSend: (String) async -> Bool
    @State private var text = ""
    @State private var sending = false
    @FocusState private var focused: Bool

    var body: some View {
        let clean = text.trimmingCharacters(in: .whitespacesAndNewlines)
        VStack(spacing: 6) {
            HStack(alignment: .bottom, spacing: 8) {
                TextField(placeholder, text: $text, axis: .vertical).lineLimit(1...5).focused($focused).themeFont(15)
                    .padding(.horizontal, 14).padding(.vertical, 10).frame(minHeight: 44)
                    .background(Theme.surface, in: RoundedRectangle(cornerRadius: 22)).overlay(RoundedRectangle(cornerRadius: 22).stroke(Theme.borderStrong))
                    .accessibilityIdentifier("composer-field")
                Button {
                    let t = text; sending = true
                    Task { if await onSend(t) { text = "" }; sending = false }
                } label: {
                    Image(systemName: "arrow.up").font(.system(size: 17, weight: .bold)).foregroundStyle(clean.isEmpty ? Theme.muted : Theme.onBrand)
                        .frame(width: 44, height: 44).background(clean.isEmpty ? Theme.surface3 : Theme.brand, in: Circle())
                }.disabled(clean.isEmpty || sending).accessibilityLabel("Send").accessibilityIdentifier("composer-send")
            }
            Text(note).themeFont(11).foregroundStyle(Theme.muted).accessibilityIdentifier("composer-note")
        }.padding(.horizontal, 14).padding(.vertical, 8).background(Theme.bg)
    }
}

struct OfflineBanner: View {
    @Environment(AppModel.self) private var model
    var body: some View {
        if model.connection == .unreachable {
            Label("You're offline. Messages wait until you're online.", systemImage: "wifi.slash").themeFont(12).foregroundStyle(Theme.warn)
                .frame(maxWidth: .infinity).padding(.vertical, 8).background(Theme.warn.opacity(0.1)).accessibilityIdentifier("offline-banner")
        }
    }
}

/// Renders a chat's items; shared by the workspace chat and the ticket chat.
struct ChatItemView: View {
    let item: ChatItem
    let workspaceName: String
    var body: some View {
        switch item.kind {
        case .mine(let t, let queued): TextBubble(text: t, mine: true, queued: queued, at: item.at)
        case .theirs(let t, let label, let sender): TextBubble(text: t, label: label, sender: sender ?? workspaceName, at: item.at)
        case .system(let t): SystemLine(text: t)
        case .card(let t): TicketCardBubble(ticket: t)
        case .question(let q): QuestionBubble(question: q)
        case .attachment(let a): AttachmentBubble(attachment: a, at: item.at)
        }
    }
}


/// What a link card says it is. The real host is always shown next to the type, and a site's icon only on that
/// site's own host: the workspace names the type, so "GitHub PR" on evil.example must not look like GitHub.
enum LinkFace {
    /// icon key -> the hosts of that site (a leading "." means any subdomain), as in the core's known_sites.json
    static let siteHosts: [String: [String]] = [
        "github": ["github.com"], "gitlab": ["gitlab.com"], "confluence": [".atlassian.net"], "jira": [".atlassian.net"],
        "linear": ["linear.app"], "notion": ["notion.so"], "figma": ["figma.com"], "miro": ["miro.com"],
        "gdocs": ["docs.google.com"], "gsheets": ["docs.google.com"], "gslides": ["docs.google.com"], "gdrive": ["drive.google.com"],
        "youtube": ["youtube.com", "youtu.be"], "loom": ["loom.com"], "slack": [".slack.com"], "teams": ["teams.microsoft.com"],
        "sharepoint": [".sharepoint.com"], "trello": ["trello.com"], "dropbox": ["dropbox.com"],
    ]

    static func host(_ url: String?) -> String {
        let h = (SafeLink.host(url) ?? "").lowercased()
        return h.hasPrefix("www.") ? String(h.dropFirst(4)) : h
    }

    /// Text from the workspace on one line: control, format (bidi, invisible) and line-break characters go, at most `max`.
    static func oneLine(_ text: String?, max: Int) -> String? {
        guard let text else { return nil }
        var kept = String.UnicodeScalarView()
        for u in text.unicodeScalars {
            switch u.properties.generalCategory {
            case .format: continue
            case .control, .lineSeparator, .paragraphSeparator: kept.append(" ")
            default: kept.append(u)
            }
        }
        let t = String(kept).split(whereSeparator: \.isWhitespace).joined(separator: " ")
        return t.isEmpty ? nil : String(t.prefix(max))
    }

    /// The link type as shown: one line, at most 32 characters; none when it looks like an address (a dot, so
    /// no "github.com" in a type that could pass for the host).
    static func type(_ raw: String?) -> String? {
        guard let t = oneLine(raw, max: 32), !t.contains("."), !t.contains("\u{FF0E}"), !t.contains("\u{3002}") else { return nil }
        return t
    }

    /// "<type> · <host>", or the host alone when there is no (usable) type.
    static func subtitle(type raw: String?, url: String?) -> String {
        let h = host(url)
        guard let t = type(raw) else { return h }
        return h.isEmpty ? t : "\(t) · \(h)"
    }

    /// The icon key to draw: a site's key only when the address is on that site, else "link". Other keys (an
    /// add-on's own icon) are not a site and pass.
    static func icon(_ icon: String?, url: String?) -> String {
        guard let key = icon, !key.isEmpty else { return "link" }
        guard let hosts = siteHosts[key] else { return LinkTile.colors[key] == nil ? key : "link" }
        let h = host(url)
        let ok = hosts.contains { $0.hasPrefix(".") ? h.hasSuffix($0) : (h == $0 || h.hasSuffix("." + $0)) }
        return ok ? key : "link"
    }
}

/// The tile of a link: a known site's colour and letters, else the link symbol (same keys as the dashboard).
struct LinkTile: View {
    let icon: String?
    let mono: String?
    static let colors: [String: UInt32] = [
        "github": 0x2b3137, "gitlab": 0x2b3137, "confluence": 0x1868db, "notion": 0xe8eaed, "figma": 0xa259ff,
        "youtube": 0xe5302a, "gdocs": 0x2f7cf6, "gdrive": 0x2f7cf6, "jira": 0x2684ff, "linear": 0x5e6ad2, "gslides": 0xf4b400,
        "slack": 0x4a154b, "miro": 0xffd02f, "gsheets": 0x1e8e3e, "loom": 0x625df5, "teams": 0x5b5fc7, "sharepoint": 0x038387,
        "trello": 0x0c66e4, "dropbox": 0x0061fe,
    ]
    static let darkText: Set<String> = ["notion", "miro", "gslides"]
    var body: some View {
        let key = icon ?? "link", letters = String((mono ?? "").prefix(3))
        ZStack {
            if key == "link" || letters.isEmpty {
                Image(systemName: "link").foregroundStyle(Theme.brand)
            } else {
                Text(letters).themeFont(12, .bold).foregroundStyle(Self.darkText.contains(key) ? Color(hex: 0x111111) : .white)
            }
        }
        .frame(width: 34, height: 34)
        .background(Self.colors[key].map { Color(hex: $0) } ?? Theme.surface3, in: RoundedRectangle(cornerRadius: 8))
    }
}

/// An add-on's status of a link (open, merged, unlisted …) as a small capsule.
struct LinkStatus: View {
    let text: String
    var body: some View {
        let tone: Color = ["open", "live", "public", "published"].contains(text) ? Theme.brand
            : text == "merged" ? Theme.purple : ["review", "draft"].contains(text) ? Theme.warn : Theme.muted
        Text(text).themeFont(11, .semibold).foregroundStyle(tone).padding(.horizontal, 8).padding(.vertical, 2)
            .overlay(Capsule().stroke(tone.opacity(0.6)))
    }
}
