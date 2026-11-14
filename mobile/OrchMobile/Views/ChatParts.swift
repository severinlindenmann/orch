import SwiftUI

/// Pieces shared by the chat screens: avatar, bubbles, cards, composer. Original messenger look in the orch dark theme.

struct KeyTag: View {
    let key: String?
    @ScaledMetric(relativeTo: .caption) private var size: CGFloat = 12
    var body: some View {
        if let key { Text(key).font(.system(size: size, design: .monospaced)).foregroundStyle(Theme.muted) }
    }
}

/// One status colour set for every screen: Working = green, Needs you = amber, Done = grey (a failure stays red).
extension TopicStatus {
    var tone: Color {
        switch self {
        case .working: Theme.brand
        case .waitingOnYou, .review: Theme.warn
        case .didntWork, .stopped: Theme.danger
        case .done, .dropped, .paused, .backlog: Theme.muted
        }
    }
}

struct StatusPill: View {
    let status: Ticket.Status
    let kind: String
    var text: String {
        // The snapshot status decides Done; only a failure or stop keeps its own sign (a done ticket may arrive as note/ack).
        switch status { case .needsYou: "Needs your OK"; case .review: "Ready for review"; case .paused: "Paused"; case .backlog: "Not started"; case .working: "Working"; case .done: kind == "failure" ? "Did not work" : (kind == "stopped" ? "Stopped" : "Done") }
    }
    var color: Color {
        switch status {
        case .needsYou: TopicStatus.waitingOnYou.tone; case .review: TopicStatus.review.tone; case .paused: TopicStatus.paused.tone; case .backlog: TopicStatus.backlog.tone
        case .working: TopicStatus.working.tone
        case .done: (kind == "failure" ? TopicStatus.didntWork : kind == "stopped" ? .stopped : .done).tone
        }
    }
    var body: some View {
        Text(text).themeFont(11, .semibold).foregroundStyle(color).padding(.horizontal, 8).padding(.vertical, 3)
            .overlay(Capsule(style: .continuous).stroke(color.opacity(0.6)))
    }
}

struct ProgressBar: View {
    let done: Int, total: Int
    var body: some View {
        GeometryReader { g in
            ZStack(alignment: .leading) {
                Capsule(style: .continuous).fill(Theme.surface3)
                Capsule(style: .continuous).fill(Theme.brand).frame(width: g.size.width * Self.fraction(done: done, total: total))
            }
        }.frame(height: 4).accessibilityHidden(true)
    }
    /// Filled share, clamped to 0...1 (done above total or below zero; total 0 is empty).
    static func fraction(done: Int, total: Int) -> CGFloat {
        guard total > 0 else { return 0 }
        return min(1, max(0, CGFloat(done) / CGFloat(total)))
    }
}

struct AttachmentBubble: View {
    let attachment: TicketSnapshot.Attachment
    var at: String = ""
    var body: some View {
        HStack {
            HStack(alignment: .bottom, spacing: 8) {
                AttachmentTile(attachment: attachment, large: true)
                Text(ChatBuilder.timeText(at)).themeFont(12).foregroundStyle(Theme.muted)
            }.padding(10).background(Theme.surface2, in: RoundedRectangle(cornerRadius: Theme.Radius.l, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: Theme.Radius.l, style: .continuous).stroke(Theme.border))
            Spacer(minLength: 48)
        }.accessibilityIdentifier("attachment-\(attachment.kind)")
    }
}

/// Image (only from the relay blob, never from an arbitrary address), link or file.
struct AttachmentTile: View {
    let attachment: TicketSnapshot.Attachment
    var large = false
    /// Set for a relay picture: the picture is its own open button (a failed one tries again on a tap instead).
    var onOpen: (() -> Void)? = nil
    static func opensItself(_ attachment: TicketSnapshot.Attachment) -> Bool {
        attachment.kind == "image" && attachment.blobId.map(BlobID.isValid) == true
    }
    var body: some View {
        switch attachment.kind {
        case "image":
            if let id = attachment.blobId, BlobID.isValid(id) {
                VStack(alignment: .leading, spacing: 6) {
                    BlobImage(id: id, open: onOpen.map { BlobImage.Open(label: "Open \(attachment.label ?? "picture")", identifier: "image-\(attachment.id)", action: $0) }).frame(maxWidth: .infinity).frame(height: large ? 140 : 84).clipShape(RoundedRectangle(cornerRadius: Theme.Radius.s, style: .continuous))
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
                HStack(spacing: 0) {  // the registrable domain never truncates; the type gives way first, then the host's head
                    let (sub, dom) = LinkFace.hostParts(a.url)
                    Text(LinkFace.type(a.linkType, url: a.url) + " · ").lineLimit(1).truncationMode(.tail)
                    if !sub.isEmpty { Text(sub).lineLimit(1).truncationMode(.head).layoutPriority(1) }
                    Text(dom).fontWeight(.semibold).foregroundStyle(Theme.text).lineLimit(1)
                        .fixedSize(horizontal: true, vertical: false).layoutPriority(2)
                }.themeFont(12).foregroundStyle(Theme.muted)
                .accessibilityElement(children: .ignore).accessibilityLabel(LinkFace.subtitle(type: a.linkType, url: a.url))
            }
            Spacer(minLength: 0)
            if let s = a.status, !s.isEmpty { LinkStatus(text: s) }
        }.foregroundStyle(Theme.text)
        return Group { if let u = SafeLink.url(a.url) { Link(destination: u) { inner } } else { inner } }
            .accessibilityIdentifier("link-card")
    }
    private func row(symbol: String, title: String, sub: String) -> some View {
        let inner = HStack(spacing: 10) {
            Image(systemName: symbol).foregroundStyle(Theme.brand).frame(width: 34, height: 34).background(Theme.surface3, in: RoundedRectangle(cornerRadius: Theme.Radius.avatar(34), style: .continuous))
            VStack(alignment: .leading, spacing: 2) { Text(title).themeFont(14, .semibold).lineLimit(1); Text(sub).themeFont(12).foregroundStyle(Theme.muted).lineLimit(1) }
            Spacer(minLength: 0)
        }.foregroundStyle(Theme.text)
        return Group {
            if attachment.kind != "file", let u = SafeLink.url(attachment.url) { Link(destination: u) { inner } } else { inner }
        }
    }
}

/// What a picture from the relay shows while it is not drawn.
enum BlobImageState: Equatable {
    case loading, loaded, unavailable, failed
    /// No bytes: the relay could not be reached (try again); bytes that are no picture stay unavailable.
    static func after(data: Data?, isImage: Bool) -> BlobImageState {
        guard data != nil else { return .failed }
        return isImage ? .loaded : .unavailable
    }
    var text: String? {
        switch self {
        case .loading, .loaded: nil
        case .unavailable: "Picture not available"
        case .failed: "Couldn't load · Tap to try again"
        }
    }
    /// A tap on a picture that failed tries again; otherwise it opens the picture.
    var tapRetries: Bool { self == .failed }
}

/// Loads an image through the relay (paired credentials): loading, not available, or a failure with a tap to try again
/// (also tried again by itself once the phone is back online).
struct BlobImage: View {
    /// The picture opens on a tap (it is its own button, so a failed picture can take the tap to try again).
    struct Open { let label: String; let identifier: String; let action: () -> Void }
    @Environment(AppModel.self) private var model
    let id: String
    var open: Open? = nil
    @State private var image: UIImage?
    @State private var state: BlobImageState = .loading
    @State private var attempt = 0
    private static let retryLabel = "Picture couldn't load. Try again"
    var body: some View {
        if let open {
            Button { if state.tapRetries { attempt += 1 } else { open.action() } } label: { picture }
                .buttonStyle(PressStyle())
                .accessibilityLabel(state.tapRetries ? Self.retryLabel : open.label)
                .accessibilityIdentifier(state.tapRetries ? "image-retry-\(id)" : open.identifier)
                .accessibilityValue(value)
        } else {
            picture
                .overlay {
                    if state.tapRetries {
                        Button { attempt += 1 } label: { Color.clear.contentShape(Rectangle()) }
                            .buttonStyle(.plain).accessibilityLabel(Self.retryLabel).accessibilityIdentifier("image-retry-\(id)")
                    }
                }
                .accessibilityValue(value)
        }
    }
    private var value: String { state == .loading ? "Loading" : state.text ?? "" }
    @ViewBuilder private var symbol: some View {
        if state == .loading { ProgressView().tint(Theme.muted) }
        else { Image(systemName: state == .failed ? "arrow.clockwise" : "photo").font(.system(size: 24)) }
    }
    private var picture: some View {
        ZStack {
            Theme.surface3
            if let image { Image(uiImage: image).resizable().scaledToFill() }
            else {
                // A small thumbnail keeps only the symbol (the words stay in the accessibility value).
                ViewThatFits(in: .vertical) {
                    VStack(spacing: 6) {
                        symbol
                        if let text = state.text { Text(text).themeFont(12).multilineTextAlignment(.center).fixedSize(horizontal: false, vertical: true) }
                    }
                    symbol
                }.foregroundStyle(Theme.muted).padding(8)
            }
        }.clipped()
            .task(id: "\(id)#\(attempt)#\(model.connection == .unreachable)") {
                guard image == nil else { return }
                if let hit = Thumbnail.cached(id: id) { image = hit; state = .loaded; return }
                state = .loading
                let data = await model.blob(id)
                let picture: UIImage? = if let data { await Thumbnail.decoded(id: id, data: data) } else { nil }
                image = picture
                state = BlobImageState.after(data: data, isImage: picture != nil)
            }
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

/// What a link card says it is (one rule for every link card; the dashboard has the same one).
/// - Type: only a known site's name from the fixed table, and only on that site's own address; else "Link".
/// - Host: the registrable domain (evil.example) in its own text that never truncates, the rest of the host
///   before it, truncated from the head.
/// - Icon: a site's icon only on that site's own host.
enum LinkFace {
    /// icon key -> the hosts of that site (a leading "." means any subdomain), mirrored from the core's known_sites.json
    static let siteHosts: [String: [String]] = [
        "github": ["github.com"], "gitlab": ["gitlab.com"], "confluence": [".atlassian.net"], "jira": [".atlassian.net"],
        "linear": ["linear.app"], "notion": ["notion.so"], "figma": ["figma.com"], "miro": ["miro.com"],
        "gdocs": ["docs.google.com"], "gsheets": ["docs.google.com"], "gslides": ["docs.google.com"], "gdrive": ["drive.google.com"],
        "youtube": ["youtube.com", "youtu.be"], "loom": ["loom.com"], "slack": [".slack.com"], "teams": ["teams.microsoft.com"],
        "sharepoint": [".sharepoint.com"], "trello": ["trello.com"], "dropbox": ["dropbox.com"],
    ]
    /// site name (lowercased) -> icon key, mirrored from known_sites.json
    static let siteNames: [String: String] = [
        "github": "github", "gitlab": "gitlab", "confluence": "confluence", "jira": "jira", "linear": "linear",
        "notion": "notion", "figma": "figma", "miro": "miro", "google docs": "gdocs", "google sheets": "gsheets",
        "google slides": "gslides", "google drive": "gdrive", "youtube": "youtube", "loom": "loom", "slack": "slack",
        "teams": "teams", "sharepoint": "sharepoint", "trello": "trello", "dropbox": "dropbox",
    ]
    /// two-part public suffixes common enough to matter (no full list on the phone)
    static let twoPartSuffixes: Set<String> = [
        "co.uk", "org.uk", "ac.uk", "gov.uk", "com.au", "net.au", "org.au", "co.nz", "co.jp", "ne.jp", "or.jp",
        "com.br", "com.cn", "com.mx", "co.in", "co.za", "com.tr", "com.sg", "com.hk", "co.kr", "github.io", "gitlab.io",
    ]

    static func host(_ url: String?) -> String {
        let h = (SafeLink.host(url) ?? "").lowercased()
        return h.hasPrefix("www.") ? String(h.dropFirst(4)) : h
    }

    /// The registrable part of a host (eTLD+1): "github.com.evil.example" -> "evil.example". An IP stays whole.
    static func domain(_ host: String) -> String {
        let parts = host.split(separator: ".").map(String.init)
        if parts.count <= 2 || parts.allSatisfy({ Int($0) != nil }) || host.contains(":") { return host }
        let n = twoPartSuffixes.contains(parts.suffix(2).joined(separator: ".")) ? 3 : 2
        return parts.suffix(n).joined(separator: ".")
    }

    /// (the host before the domain, e.g. "gist.", the domain)
    static func hostParts(_ url: String?) -> (String, String) {
        let h = host(url), d = domain(h)
        return (String(h.dropLast(d.count)), d)
    }

    static func onSite(_ key: String, url: String?) -> Bool {
        let h = host(url)
        return (siteHosts[key] ?? []).contains { $0.hasPrefix(".") ? h.hasSuffix($0) : (h == $0 || h.hasSuffix("." + $0)) }
    }

    /// The link type as shown: only known site names from the fixed table, each only on that site's own
    /// address. Anything else (free text, add-on labels the phone can not check) is "Link".
    static func type(_ raw: String?, url: String?) -> String {
        let parts = (raw ?? "").components(separatedBy: " · ").filter { p in
            siteNames[p.lowercased()].map { onSite($0, url: url) } ?? false
        }
        return parts.isEmpty ? "Link" : parts.joined(separator: " · ")
    }

    /// One line for tests and accessibility: "<type> · <host>".
    static func subtitle(type raw: String?, url: String?) -> String {
        let h = host(url)
        return h.isEmpty ? type(raw, url: url) : "\(type(raw, url: url)) · \(h)"
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

    /// The icon key to draw: a site's key only on that site's own host, else "link". An add-on's own icon (not a
    /// site's) passes.
    static func icon(_ icon: String?, url: String?) -> String {
        guard let key = icon, !key.isEmpty else { return "link" }
        guard siteHosts[key] != nil else { return LinkTile.colors[key] == nil ? key : "link" }
        return onSite(key, url: url) ? key : "link"
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
        .background(Self.colors[key].map { Color(hex: $0) } ?? Theme.surface3, in: RoundedRectangle(cornerRadius: Theme.Radius.avatar(34), style: .continuous))
    }
}

/// An add-on's status of a link (open, merged, unlisted …) as a small capsule.
struct LinkStatus: View {
    let text: String
    var body: some View {
        let tone: Color = ["open", "live", "public", "published"].contains(text) ? Theme.brand
            : text == "merged" ? Theme.purple : ["review", "draft"].contains(text) ? Theme.warn : Theme.muted
        Text(text).themeFont(11, .semibold).foregroundStyle(tone).padding(.horizontal, 8).padding(.vertical, 2)
            .overlay(Capsule(style: .continuous).stroke(tone.opacity(0.6)))
    }
}

/// Conversation message; voice and question cards are routed by ConversationView.
struct MessageBubble: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dynamicTypeSize) private var typeSize
    let item: ConvItem
    let conversationId: ConversationID
    let conversationLanguage: String
    let workspaceName: String
    let quotedText: String?
    let onRetry: (() -> Void)?
    let onDiscard: (() -> Void)?
    var onOpenArtifact: (String) -> Void = { _ in }
    var attachments: [TicketSnapshot.Attachment] = []
    var onReply: (() -> Void)? = nil
    /// "Try again later" next to the clock while the relay is throttling this message.
    var waitNote: String? = nil
    var hugsContent = false
    private var mine: Bool { item.side == .me }

    var body: some View {
        HStack(spacing: 0) {
            if mine { Spacer(minLength: typeSize.isAccessibilitySize ? 8 : 64) }
            BubbleContentLayout(hugsContent: hugsContent) {
                VStack(alignment: .leading, spacing: 8) {
                    if let quotedText {
                        HStack(spacing: 8) {
                            Rectangle().fill(Theme.brand).frame(width: 3)
                            Text(quotedText).themeFont(13).foregroundStyle(mine ? Theme.mineStamp : Theme.muted).lineLimit(2)
                        }.fixedSize(horizontal: false, vertical: true)
                    }
                    if let label = item.label {
                        Text(label).themeFont(12, .semibold).foregroundStyle(label == "DID NOT WORK" ? Theme.danger : Theme.brand)
                    }
                    if !item.text.isEmpty {
                        if inlineStamp { InlineStampLayout { textView; stamp(onMedia: false) } } else { textView }
                    }
                    ForEach(item.attachments) { attachment in
                        if attachment.kind == .image, BlobID.isValid(attachment.blobId) {
                            BlobImage(id: attachment.blobId, open: .init(label: "Open \(attachment.name)", identifier: "image-\(attachment.id)") { onOpenArtifact(attachment.blobId) })
                                .frame(height: 190).clipShape(RoundedRectangle(cornerRadius: mediaOnly ? Theme.Radius.l : Theme.Radius.s, style: .continuous))
                        } else if BlobID.isValid(attachment.blobId), attachment.kind == .file {
                            Button { onOpenArtifact(attachment.blobId) } label: { fileRowWithTime(attachment.name, size: attachment.size, isLast: isLastFile(attachment.id)) }
                                .buttonStyle(PressStyle()).accessibilityLabel("Open \(attachment.name)").accessibilityIdentifier("file-\(attachment.id)")
                        } else { fileRowWithTime(attachment.name, size: attachment.size, isLast: isLastFile(attachment.id)) }
                    }
                    ForEach(item.queuedFiles, id: \.file) { file in
                        if file.kind == .image, let pending = model.outbox.item(clientId: item.clientId ?? "") {
                            QueuedConversationImage(url: model.outbox.fileURL(pending, file), name: file.name)
                        } else { fileRowWithTime(file.name, size: file.size, isLast: file.file == item.queuedFiles.last?.file) }
                    }
                    ForEach(item.artifacts) { artifact in
                        Button { onOpenArtifact(artifact.id) } label: {
                            HStack(spacing: 10) {
                                Image(systemName: Self.symbol(artifact.kind)).themeFont(20).foregroundStyle(Theme.brand).frame(width: 42, height: 48)
                                    .background(Theme.surface3, in: RoundedRectangle(cornerRadius: Theme.Radius.avatar(42), style: .continuous))
                                VStack(alignment: .leading, spacing: 4) {
                                    Text(artifact.label ?? "Preview").themeFont(14, .semibold).multilineTextAlignment(.leading)
                                    Text("Open ›").themeFont(13).foregroundStyle(Theme.brand)
                                }
                                Spacer(minLength: 0)
                            }.frame(minHeight: 44).contentShape(Rectangle())
                        }.buttonStyle(PressStyle()).accessibilityLabel("Open \(artifact.label ?? "preview")")
                            .accessibilityIdentifier("artifact-\(artifact.id)")
                    }
                    if let location = item.location {
                        LocationCard(location: location).accessibilityIdentifier("location-\(item.id)")
                    }
                    if let feedback = item.feedback {
                        VStack(alignment: .leading, spacing: 4) {
                            Label(feedback.verdict == .approve ? "Looks good" : "Changes asked", systemImage: feedback.verdict == .approve ? "checkmark.circle" : "pencil")
                            Text("\(feedback.pins.count) comments").foregroundStyle(mine ? Theme.mineStamp : Theme.muted)
                        }.themeFont(15)
                    }
                    if footerStamp {
                        if mine {
                            ReceiptView(receipt: item.receipt ?? .sent, time: ChatBuilder.timeText(item.at), note: waitNote, onRetry: onRetry, onDiscard: onDiscard,
                                        tint: Theme.mineStamp, waitingWord: waitingWord)
                                .frame(maxWidth: .infinity, alignment: .trailing)
                        } else {
                            Text(ChatBuilder.timeText(item.at)).themeFont(12).foregroundStyle(Theme.muted).frame(maxWidth: .infinity, alignment: .trailing)
                        }
                    }
                }.padding(mediaOnly ? 0 : 12).foregroundStyle(Theme.text)
                    // Photo and map run edge to edge: the time sits on the picture on a dark backing (readable on any picture).
                    .overlay(alignment: .bottomTrailing) { if mediaOnly && !footerStamp { stamp(onMedia: true).padding(8) } }
                    .background(mediaOnly ? Color.clear : (mine ? Theme.mineFill : Theme.surface2), in: RoundedRectangle(cornerRadius: Theme.Radius.l, style: .continuous))
                    .contextMenu {
                        Button { UIPasteboard.general.string = item.text } label: { Label("Copy", systemImage: "doc.on.doc") }.accessibilityIdentifier("copy-\(item.id)")
                        if !mine && item.canPlay {
                            Button { model.play(item, in: conversationId) } label: { Label("Listen", systemImage: "speaker.wave.2") }.accessibilityIdentifier("listen-\(item.id)")
                        }
                    }
                    .accessibilityAction(named: "Copy") { UIPasteboard.general.string = item.text }
                    .modifier(BubbleActions(item: item, conversationId: conversationId, onReply: onReply, onRetry: onRetry, onDiscard: onDiscard))
            }
            if !mine { Spacer(minLength: ChatBubbleLayout.agentTrailingSpace(for: typeSize)) }
        }
    }
    private var messageText: Text {
        item.side == .them && conversationId.ticket != nil ? Text(ArtifactMentions.attributed(item.text, attachments: attachments)) : Text(item.text)
    }
    /// The message text alone (the time is placed beside it, never padded into it); a mentioned file opens in the viewer.
    private var textView: some View {
        messageText.themeFont(17).textSelection(.enabled).fixedSize(horizontal: false, vertical: true)
            .environment(\.openURL, OpenURLAction { url in
                guard let id = ArtifactMentions.attachmentId(from: url) else { return .systemAction }
                onOpenArtifact(id)
                return .handled
            })
    }
    private var waitingWord: Bool { ReceiptView.showsWaitingWord(offline: model.connection == .unreachable, note: waitNote) }
    private func isLastFile(_ attachmentId: String) -> Bool { item.queuedFiles.isEmpty && attachmentId == item.attachments.last?.id }
    /// Only text and quote: the bubble is as wide as its text (no stretch to the screen edge).
    static func hugs(_ item: ConvItem) -> Bool {
        item.attachments.isEmpty && item.queuedFiles.isEmpty && item.artifacts.isEmpty && item.location == nil && item.feedback == nil
    }
    private var failed: Bool { if case .failed? = item.receipt { true } else { false } }
    /// Retry/Discard or a "Try again later" note need their own line; else the time and ticks sit inline.
    private var needsOwnLine: Bool { mine && (failed || (waitNote != nil && item.receipt == .queued)) }
    /// A photo or a map alone: no frame around it (a failed or waiting one keeps its frame for the line below).
    private var mediaOnly: Bool {
        guard !needsOwnLine, item.text.isEmpty, quotedText == nil, item.label == nil, item.artifacts.isEmpty, item.feedback == nil, item.queuedFiles.isEmpty else { return false }
        if item.location != nil { return item.attachments.isEmpty }
        return item.attachments.count == 1 && item.attachments[0].kind == .image && BlobID.isValid(item.attachments[0].blobId)
    }
    /// Files alone: one compact row each, the time inline at the trailing edge of the last.
    private var filesOnly: Bool {
        item.text.isEmpty && item.location == nil && item.artifacts.isEmpty && item.feedback == nil
            && !(item.attachments.isEmpty && item.queuedFiles.isEmpty)
            && item.attachments.allSatisfy { !($0.kind == .image && BlobID.isValid($0.blobId)) } && item.queuedFiles.allSatisfy { $0.kind != .image }
    }
    private var inlineStamp: Bool { !needsOwnLine && Self.hugs(item) && !item.text.isEmpty }
    private var footerStamp: Bool { needsOwnLine || !(inlineStamp || mediaOnly || filesOnly) }
    @ViewBuilder private func stamp(onMedia: Bool) -> some View {
        Group {
            if mine { ReceiptView(receipt: item.receipt ?? .sent, time: ChatBuilder.timeText(item.at), inline: true, tint: onMedia ? .white : Theme.mineStamp, waitingWord: waitingWord) }
            else { Text(ChatBuilder.timeText(item.at)).themeFont(12).foregroundStyle(onMedia ? .white : Theme.muted) }
        }.padding(.horizontal, onMedia ? 8 : 0).padding(.vertical, onMedia ? 3 : 0)
            .background(onMedia ? Color.black.opacity(0.6) : Color.clear, in: Capsule())
    }
    @ViewBuilder private func fileRowWithTime(_ name: String, size: Int, isLast: Bool) -> some View {
        if filesOnly && !needsOwnLine && isLast {
            HStack(alignment: .bottom, spacing: 8) { fileRow(name, size: size); Spacer(minLength: 0); stamp(onMedia: false) }
        } else { fileRow(name, size: size) }
    }

    private static func symbol(_ kind: String) -> String {
        switch kind.lowercased() {
        case "html", "page", "text/html": "globe"
        case "image": "photo"
        case "pr", "commit": "arrow.triangle.branch"
        case "link": "link"
        default: "doc"
        }
    }
    private func fileRow(_ name: String, size: Int) -> some View {
        HStack(spacing: 10) {
            Image(systemName: "doc").themeFont(20).foregroundStyle(Theme.brand).frame(width: 42, height: 48).background(Theme.surface3, in: RoundedRectangle(cornerRadius: Theme.Radius.avatar(42), style: .continuous))
            VStack(alignment: .leading, spacing: 4) {
                Text(name).themeFont(14, .semibold).fixedSize(horizontal: false, vertical: true)
                Text(ByteCountFormatter.string(fromByteCount: Int64(size), countStyle: .file)).themeFont(13).foregroundStyle(Theme.muted)
            }
        }
    }
}

private struct QueuedConversationImage: View {
    let url: URL
    let name: String
    @State private var image: UIImage?
    var body: some View {
        ZStack {
            Theme.surface3
            if let image { Image(uiImage: image).resizable().scaledToFill() }
            else { Image(systemName: "photo").foregroundStyle(Theme.muted) }
        }.frame(height: 190).clipped().clipShape(RoundedRectangle(cornerRadius: Theme.Radius.s, style: .continuous)).accessibilityLabel(name)
            .task(id: url) {
                let key = url.path
                if let hit = Thumbnail.cached(id: key) { image = hit; return }
                let data = await Task.detached(priority: .userInitiated) { try? Data(contentsOf: url) }.value
                if let data { image = await Thumbnail.decoded(id: key, data: data) }
            }
    }
}


/// VoiceOver custom actions shared by every bubble: Reply, Retry and Discard on a failed send, Listen where the text can be read aloud.
struct BubbleActions: ViewModifier {
    @Environment(AppModel.self) private var model
    let item: ConvItem
    let conversationId: ConversationID
    var onReply: (() -> Void)?
    var onRetry: (() -> Void)?
    var onDiscard: (() -> Void)?
    private var failed: Bool { if case .failed? = item.receipt { true } else { false } }
    func body(content: Content) -> some View {
        content
            .accessibilityActions {
                if let onReply { Button("Reply", action: onReply) }
                if failed {
                    if let onRetry { Button("Retry", action: onRetry) }
                    if let onDiscard { Button("Discard", action: onDiscard) }
                }
                if item.incoming && item.canPlay { Button("Listen") { model.play(item, in: conversationId) } }
            }
    }
}

/// "Try again later" for a message the relay is throttling (HTTP 429): shown next to the clock.
enum ThrottleNote {
    static func text(for item: OutboxItem?) -> String? {
        guard let item, item.sentMessageId == nil, item.failure == nil, (item.throttleCount ?? 0) > 0 || item.retryAfter != nil else { return nil }
        return "Try again later"
    }
}


/// Measure the natural content width, capped by the width offered by the bubble's row.
private struct BubbleContentLayout: Layout {
    let hugsContent: Bool
    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        guard let content = subviews.first else { return .zero }
        guard hugsContent else { return content.sizeThatFits(proposal) }
        let ideal = content.sizeThatFits(.unspecified)
        return content.sizeThatFits(ProposedViewSize(width: min(ideal.width, proposal.width ?? ideal.width), height: proposal.height))
    }
    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        subviews.first?.place(at: bounds.origin, anchor: .topLeading, proposal: ProposedViewSize(bounds.size))
    }
}

/// A text and its time: the time sits at the bottom-trailing edge beside the text when the text keeps its lines
/// while leaving room for it, else on its own line below. Nothing is padded into the text, so selecting, copying
/// and VoiceOver get the text alone (links included).
struct InlineStampLayout: Layout {
    var spacing: CGFloat = 8
    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        frames(proposal.width, subviews).size
    }
    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let f = frames(proposal.width ?? bounds.width, subviews)
        subviews[0].place(at: bounds.origin, proposal: ProposedViewSize(f.text))
        subviews[1].place(at: CGPoint(x: bounds.minX + f.stamp.x, y: bounds.minY + f.stamp.y), proposal: .unspecified)
    }
    private func frames(_ width: CGFloat?, _ subviews: Subviews) -> (size: CGSize, text: CGSize, stamp: CGPoint) {
        guard subviews.count == 2 else { return (.zero, .zero, .zero) }
        let stamp = subviews[1].sizeThatFits(.unspecified)
        let full = subviews[0].sizeThatFits(ProposedViewSize(width: width, height: nil))
        let narrow = subviews[0].sizeThatFits(ProposedViewSize(width: width.map { max(0, $0 - stamp.width - spacing) }, height: nil))
        if narrow.height <= full.height + 0.5 {
            let size = CGSize(width: narrow.width + spacing + stamp.width, height: max(narrow.height, stamp.height))
            return (size, narrow, CGPoint(x: size.width - stamp.width, y: size.height - stamp.height + 2))
        }
        let size = CGSize(width: max(full.width, stamp.width), height: full.height + stamp.height)
        return (size, full, CGPoint(x: size.width - stamp.width, y: full.height))
    }
}
