import SwiftUI
import UIKit

// Pieces of the Review stack: the card, the comment sheet, the full-screen viewer and the overview.

// MARK: Card

struct ReviewCardView: View {
    let item: ReviewItem
    @Binding var picked: String?
    let state: String?
    let onOpen: () -> Void

    private var kindName: String {
        switch item.kind { case .draft: "Draft"; case .check: "Result"; case .link: "Link"; case .choice, .plainQuestion: "Choice"; case .plan: "Plan" }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                Text(kindName).themeFont(12, .semibold).padding(.horizontal, 10).padding(.vertical, 3)
                    .background(Theme.surface3, in: Capsule()).accessibilityIdentifier("review-kind")
                if let need = item.card.need, !need.isEmpty { Text(need).themeFont(12, .semibold).foregroundStyle(Theme.warn).lineLimit(1) }
                Spacer()
                if let key = item.question.message.key { Text(key).themeFont(12).foregroundStyle(Theme.muted) }
                Text(ShellTime.short(item.question.message.createdAt)).themeFont(12).foregroundStyle(Theme.muted)
            }
            Text(item.card.title).themeFont(21, .semibold).lineLimit(3).accessibilityAddTraits(.isHeader).accessibilityIdentifier("review-title")
            if let why = item.card.why, !why.isEmpty { Text(why).themeFont(14).foregroundStyle(Theme.muted).lineLimit(3) }
            if let preview = item.card.preview {
                CardPreviewView(item: item, preview: preview, picked: $picked, onOpen: onOpen)
            } else {
                Spacer(minLength: 0)
            }
            if !item.card.then.isEmpty {
                Text("If you approve: \(item.card.then)").themeFont(14).foregroundStyle(Theme.text).lineLimit(3).accessibilityIdentifier("review-then")
            }
            HStack(spacing: 8) {
                if item.signs {
                    Label("Face ID when you approve", systemImage: "faceid").themeFont(12, .semibold)
                        .padding(.horizontal, 10).padding(.vertical, 4).background(Theme.surface3, in: Capsule())
                        .accessibilityIdentifier("review-signs-chip")
                }
                if let state { Text(state).themeFont(12, .semibold).foregroundStyle(Theme.warn).accessibilityIdentifier("review-state") }
            }
        }
        .padding(16).frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(Theme.surface, in: RoundedRectangle(cornerRadius: Theme.Radius.l, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: Theme.Radius.l, style: .continuous).stroke(Theme.border))
    }
}

/// A preview: a file (picture, page), a document, a table, before/after, or option tiles.
struct CardPreviewView: View {
    let item: ReviewItem
    let preview: CardPreview
    @Binding var picked: String?
    let onOpen: () -> Void
    @State private var side = 2   // 0 Before, 1 After, 2 Both

    var body: some View {
        switch preview {
        case .options(let options): tiles(options)
        case .compare(let before, let after, let note):
            VStack(spacing: 6) {
                Picker("Show", selection: $side) { Text("Before").tag(0); Text("After").tag(1); Text("Both").tag(2) }
                    .pickerStyle(.segmented).accessibilityIdentifier("review-compare-side")
                HStack(spacing: 8) {
                    if side != 1 { LeafView(item: item, leaf: before, caption: "Before", onOpen: onOpen) }
                    if side != 0 { LeafView(item: item, leaf: after, caption: "After", onOpen: onOpen) }
                }
                if let note { Text(note).themeFont(12).foregroundStyle(Theme.muted) }
            }
        default: LeafView(item: item, leaf: preview, caption: nil, onOpen: onOpen)
        }
    }

    private func tiles(_ options: [CardOption]) -> some View {
        let recommended = item.question.message.body.recommended
        return ScrollView {
            LazyVGrid(columns: [GridItem(.flexible(), spacing: 8), GridItem(.flexible(), spacing: 8)], spacing: 8) {
                ForEach(options) { option in
                    Button { picked = picked == option.id ? nil : option.id } label: {
                        VStack(alignment: .leading, spacing: 4) {
                            if let p = option.preview { LeafView(item: item, leaf: p, caption: nil, onOpen: {}, compact: true).frame(height: 60) }
                            HStack {
                                Text(option.id).themeFont(13, .bold).foregroundStyle(Theme.brand)
                                Text(option.title).themeFont(15, .semibold).lineLimit(2)
                            }
                            if let t = option.text { Text(t).themeFont(12).foregroundStyle(Theme.muted).lineLimit(2) }
                            if recommended == option.title || recommended == option.id {
                                Text("Suggested").themeFont(11, .semibold).foregroundStyle(Theme.warn)
                            }
                        }.padding(10).frame(maxWidth: .infinity, minHeight: 56, alignment: .leading)
                            .background(Theme.surface2, in: RoundedRectangle(cornerRadius: Theme.Radius.m, style: .continuous))
                            .overlay(RoundedRectangle(cornerRadius: Theme.Radius.m, style: .continuous)
                                .stroke(picked == option.id ? Theme.brand : Theme.borderStrong.opacity(0.5), lineWidth: picked == option.id ? 3 : 1))
                            .overlay(alignment: .topTrailing) {
                                if picked == option.id { Text("Picked").themeFont(11, .semibold).foregroundStyle(Theme.onBrand).padding(.horizontal, 6).padding(.vertical, 2)
                                    .background(Theme.brand, in: Capsule()).padding(6) }
                            }
                    }.buttonStyle(PressStyle()).foregroundStyle(Theme.text)
                        .accessibilityIdentifier("option-\(option.id)")
                        .accessibilityLabel("\(option.id): \(option.title)")
                        .accessibilityValue(picked == option.id ? "Picked" : "")
                        .accessibilityAddTraits(picked == option.id ? .isSelected : [])
                }
            }
        }.scrollBounceBehavior(.basedOnSize)
    }
}

/// One leaf preview: picture, page, document steps or table.
struct LeafView: View {
    let item: ReviewItem
    let leaf: CardPreview
    let caption: String?
    let onOpen: () -> Void
    var compact = false
    @Environment(AppModel.self) private var model
    @State private var data: Data?
    @State private var failed = false

    var body: some View {
        VStack(spacing: 4) {
            Group {
                switch leaf {
                case .img(let src, let alt): file(src, alt: alt ?? "Picture", isPage: false)
                case .page(let src): file(src, alt: "Page", isPage: true)
                case .doc(let heading, let paras, let steps): doc(heading, paras, steps)
                case .table(let cols, let rows): table(cols, rows)
                default: EmptyView()
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(Theme.surface2, in: RoundedRectangle(cornerRadius: Theme.Radius.m, style: .continuous))
            .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.m, style: .continuous))
            .contentShape(Rectangle())
            .modifier(OpenOnTap(enabled: !compact, action: onOpen))
            if let caption { Text(caption).themeFont(12).foregroundStyle(Theme.muted) }
        }.accessibilityIdentifier("review-preview")
    }

    @ViewBuilder private func file(_ src: CardSrc, alt: String, isPage: Bool) -> some View {
        if case .unavailable = src {
            note("Open on the computer", "desktopcomputer")
        } else if let data, !isPage, let image = UIImage(data: data) {
            Image(uiImage: image).resizable().scaledToFit().accessibilityLabel(alt)
        } else if isPage, data != nil {
            VStack(spacing: 6) { Image(systemName: "doc.richtext").themeFont(28).foregroundStyle(Theme.brand); Text("Web page · tap to open").themeFont(13).foregroundStyle(Theme.muted) }
        } else if failed {
            note("Open on the computer", "desktopcomputer")
        } else {
            ProgressView().task { await load(src) }
        }
    }

    private func load(_ src: CardSrc) async {
        guard let f = item.file(for: src) else { failed = true; return }
        if let d = await model.cardFile(f) { data = d } else { failed = true }
    }

    private func note(_ text: String, _ icon: String) -> some View {
        VStack(spacing: 6) { Image(systemName: icon).themeFont(24).foregroundStyle(Theme.muted); Text(text).themeFont(13).foregroundStyle(Theme.muted) }
    }

    private func doc(_ heading: String?, _ paras: [String], _ steps: [String]) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 6) {
                if let heading { Text(heading).themeFont(15, .semibold) }
                ForEach(Array(paras.enumerated()), id: \.offset) { _, p in Text(p).themeFont(14) }
                ForEach(Array(steps.enumerated()), id: \.offset) { i, s in HStack(alignment: .top) { Text("\(i + 1).").themeFont(14, .semibold).foregroundStyle(Theme.brand); Text(s).themeFont(14) } }
            }.padding(12).frame(maxWidth: .infinity, alignment: .leading)
        }.scrollBounceBehavior(.basedOnSize)
    }

    private func table(_ cols: [String], _ rows: [[String]]) -> some View {
        ScrollView([.horizontal, .vertical]) {
            Grid(alignment: .leading, horizontalSpacing: 14, verticalSpacing: 6) {
                GridRow { ForEach(cols, id: \.self) { Text($0).themeFont(12, .semibold).foregroundStyle(Theme.muted) } }
                ForEach(Array(rows.enumerated()), id: \.offset) { _, r in GridRow { ForEach(Array(r.enumerated()), id: \.offset) { _, c in Text(c).themeFont(13) } } }
            }.padding(12)
        }
    }
}

// MARK: Comment sheet

struct ReviewCommentSheet: View {
    let item: ReviewItem
    @Binding var about: String?
    @Binding var text: String
    let pins: PinStore
    let onSend: (ReviewVerdict.Word, String?) -> Void
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var recorder: VoiceRecorder?
    @State private var working = false
    @State private var error: String?

    private var hasContent: Bool { !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || pins.count > 0 }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                Text("What should change?").themeFont(20, .semibold).accessibilityAddTraits(.isHeader)
                if item.isChoice {
                    Picker("About", selection: Binding(get: { about ?? "All" }, set: { about = $0 == "All" ? nil : $0 })) {
                        ForEach(item.optionIds + ["All"], id: \.self) { Text($0).tag($0) }
                    }.pickerStyle(.segmented).accessibilityIdentifier("comment-about")
                }
                Text("Say it or type it. The helper reads your words and tries again.").themeFont(13).foregroundStyle(Theme.muted)
                HStack(alignment: .top, spacing: 10) {
                    TextField("What should change?", text: $text, axis: .vertical).lineLimit(3...8).themeFont(16).padding(12)
                        .background(Theme.surface2, in: RoundedRectangle(cornerRadius: Theme.Radius.m, style: .continuous))
                        .accessibilityIdentifier("comment-text")
                    Button { toggleMic() } label: {
                        Image(systemName: recorder?.isRecording == true ? "stop.fill" : "mic.fill").frame(width: 48, height: 48)
                            .background(Theme.surface3, in: Circle())
                    }.disabled(working).accessibilityLabel(recorder?.isRecording == true ? "Stop recording" : "Record voice comment")
                        .accessibilityIdentifier("comment-mic")
                }
                if recorder?.isRecording == true { Text("Recording \(Int(recorder?.elapsed ?? 0))s").themeFont(14).monospacedDigit() }
                else if working { ProgressView().accessibilityLabel("Writing down what you said") }
                if let error { Text(error).themeFont(14).foregroundStyle(Theme.muted) }
                if pins.count > 0 { PinChipRow(store: pins) }
                Button { onSend(.talk, nil) } label: { Text("Send back for changes") }
                    .buttonStyle(ArtifactActionButtonStyle(primary: !(item.isChoice && about != nil))).disabled(!hasContent || working)
                    .accessibilityIdentifier("comment-send")
                if item.isChoice, let about {
                    Button { onSend(.talk, about) } label: { Text("Use \(about) with these changes") }
                        .buttonStyle(ArtifactActionButtonStyle(primary: true)).disabled(!hasContent || working)
                        .accessibilityIdentifier("comment-use")
                }
            }.padding(20)
        }
        .foregroundStyle(Theme.text).tint(Theme.brand).background(Theme.surface).preferredColorScheme(.dark)
        .presentationDetents([.medium, .large]).presentationDragIndicator(.visible)
        .onDisappear { recorder?.cancel() }   // the text stays in the card's draft
        .accessibilityIdentifier("comment-sheet")
    }

    private func toggleMic() {
        guard !working else { return }
        if recorder == nil { recorder = model.makeVoiceRecorder() }
        guard let recorder else { return }
        error = nil; working = true
        Task { @MainActor in
            defer { working = false }
            if recorder.isRecording {
                guard let segment = recorder.stop().first else { return }
                let draft = await model.voiceDraft(for: segment)
                let t = draft.transcript.trimmingCharacters(in: .whitespacesAndNewlines)
                if !t.isEmpty { text = text.isEmpty ? t : text + " " + t }   // v1: the transcript only, no audio is sent
                recorder.cancel()
            } else {
                do { try await recorder.start() } catch { self.error = recorder.error ?? "Could not start the microphone." }
            }
        }
    }
}

// MARK: Viewer

/// The address a card's `open` field names, parsed the way a browser does; the person sees the host and the re-serialised address opens.
enum CardOpenLink {
    static func parse(_ s: String?) -> (host: String, url: URL)? {
        guard let s, let c = URLComponents(string: s.trimmingCharacters(in: .whitespacesAndNewlines)),
              let scheme = c.scheme?.lowercased(), ["http", "https"].contains(scheme),
              let host = c.host, !host.isEmpty, c.user == nil, c.password == nil, let url = c.url else { return nil }
        return (host, url)
    }
}

struct ReviewViewer: View {
    let item: ReviewItem
    let pins: PinStore
    let picked: String?
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @Environment(\.openURL) private var openURL
    @State private var spot = false
    @State private var side = 2
    @State private var datas: [Int: Data] = [:]

    private var leaves: [(String?, CardPreview)] {
        switch item.card.preview {
        case .compare(let b, let a, _)?: return side == 0 ? [("Before", b)] : side == 1 ? [("After", a)] : [("Before", b), ("After", a)]
        case .options(let o)?: return o.filter { picked == nil || $0.id == picked }.compactMap { opt in opt.preview.map { (opt.id + " · " + opt.title, $0) } }
        case let p?: return [(nil, p)]
        case nil: return []
        }
    }

    var body: some View {
        VStack(spacing: 8) {
            HStack {
                Text(item.card.title).themeFont(18, .semibold).lineLimit(1).accessibilityAddTraits(.isHeader)
                Spacer()
                Button { dismiss() } label: { Image(systemName: "xmark").frame(width: 44, height: 44).background(Theme.surface3, in: Circle()) }
                    .accessibilityLabel("Close").accessibilityIdentifier("viewer-close")
            }
            if case .compare? = item.card.preview {
                Picker("Show", selection: $side) { Text("Before").tag(0); Text("After").tag(1); Text("Both").tag(2) }.pickerStyle(.segmented)
            }
            if spot { Text("Tap the picture to add a comment").themeFont(14).foregroundStyle(Theme.muted); if pins.count > 0 { PinChipRow(store: pins) } }
            HStack(spacing: 8) {
                ForEach(Array(leaves.enumerated()), id: \.offset) { _, entry in
                    VStack(spacing: 4) {
                        leaf(entry.1).frame(maxWidth: .infinity, maxHeight: .infinity).background(Theme.bg)
                        if let c = entry.0 { Text(c).themeFont(12).foregroundStyle(Theme.muted) }
                    }
                }
            }
            HStack(spacing: 10) {
                if let link = CardOpenLink.parse(item.card.open) {
                    Button { openURL(link.url) } label: { Text("Open \(link.host)") }.buttonStyle(ArtifactActionButtonStyle())
                        .accessibilityIdentifier("viewer-open").accessibilityHint("Opens in your browser")
                }
                Button { spot.toggle() } label: { Label(spot ? "Done spotting" : "Spot", systemImage: "mappin.and.ellipse") }
                    .buttonStyle(ArtifactActionButtonStyle(primary: spot)).accessibilityIdentifier("viewer-spot")
                if spot { Button("Add comment here") { pins.addAtCenter?() }.buttonStyle(ArtifactActionButtonStyle()).accessibilityIdentifier("viewer-add-pin") }
            }
        }
        .padding(16).background(Theme.bg).foregroundStyle(Theme.text).preferredColorScheme(.dark)
        .sheet(isPresented: Binding(get: { pins.editing != nil }, set: { if !$0 { pins.cancelEdit() } })) { PinEditorSheet(store: pins) }
        .accessibilityIdentifier("review-viewer")
    }

    @ViewBuilder private func leaf(_ p: CardPreview) -> some View {
        switch p {
        case .img(let src, _), .page(let src):
            ViewerFile(item: item, src: src, isPage: { if case .page = p { true } else { false } }(), spot: spot, pins: pins)
        default: LeafView(item: item, leaf: p, caption: nil, onOpen: {})
        }
    }
}

private struct ViewerFile: View {
    let item: ReviewItem
    let src: CardSrc
    let isPage: Bool
    let spot: Bool
    let pins: PinStore
    @Environment(AppModel.self) private var model
    @State private var data: Data?
    @State private var failed = false

    var body: some View {
        Group {
            if case .unavailable = src { Text("Open on the computer").themeFont(14).foregroundStyle(Theme.muted) }
            else if let data {
                if isPage, let html = String(data: data, encoding: .utf8) {
                    HTMLSurface(content: .publish(.page(html: html, name: "page.html")), commentMode: spot, store: pins)
                } else { ImageSurface(data: data, commentMode: spot, store: pins) }   // pinch to zoom
            } else if failed { Text("Open on the computer").themeFont(14).foregroundStyle(Theme.muted) }
            else { ProgressView() }
        }.task {
            guard let f = item.file(for: src) else { failed = true; return }
            if let d = await model.cardFile(f) { data = d } else { failed = true }
        }
    }
}

// MARK: Overview

struct ReviewOverview: View {
    let waiting: [ReviewItem]
    let answered: [ReviewItem]
    let later: Set<String>
    let workspace: String
    let onJump: (String) -> Void
    let onChange: (String) -> Void
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List {
                Section("Waiting") {
                    ForEach(waiting) { item in
                        Button { onJump(item.id) } label: {
                            HStack { Text(item.card.title).lineLimit(2); Spacer(); if later.contains(item.id) { Text("Later").themeFont(12).foregroundStyle(Theme.warn) } }
                                .frame(minHeight: 44)
                        }.accessibilityElement(children: .combine).accessibilityIdentifier("overview-\(item.id)")
                    }
                    if waiting.isEmpty { Text("Nothing is waiting.").foregroundStyle(Theme.muted) }
                }
                if !answered.isEmpty {
                    Section("Answered") {
                        ForEach(answered) { item in
                            let outbox = model.verdictItem(for: item.id)
                            let result = ReviewStackRules.result(for: item.id, workspace: workspace, in: model.messages)
                            let state = ReviewStateText.text(ReviewStackRules.state(item: outbox, result: result))
                            HStack {
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(item.card.title).lineLimit(2)
                                    Text(state ?? "Answered").themeFont(12).foregroundStyle(Theme.muted).accessibilityIdentifier("overview-state")
                                }
                                Spacer()
                                if outbox?.canChangeVerdict == true {   // M4: only while it is still on this phone
                                    Button("Change") { onChange(item.id) }.buttonStyle(.borderless).foregroundStyle(Theme.brand)
                                        .frame(minHeight: 44).accessibilityIdentifier("overview-change-\(item.id)")
                                }
                            }
                        }
                    }
                }
            }
            .scrollContentBackground(.hidden).background(Theme.bg).navigationTitle("All").navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() }.accessibilityIdentifier("overview-done") } }
        }.preferredColorScheme(.dark).tint(Theme.brand).presentationDetents([.large])
    }
}

/// A tap that opens the viewer; absent on the small previews inside option tiles (the tile's own button gets the tap).
private struct OpenOnTap: ViewModifier {
    let enabled: Bool
    let action: () -> Void
    func body(content: Content) -> some View {
        if enabled { content.onTapGesture(perform: action) } else { content.allowsHitTesting(false) }
    }
}
