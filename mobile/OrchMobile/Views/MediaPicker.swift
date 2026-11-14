import SwiftUI
import PhotosUI
import UIKit
import UniformTypeIdentifiers
import VisionKit
@preconcurrency import MapKit
@preconcurrency import CoreLocation

/// What the person picked, ready for the composer.
enum MediaSelection: Equatable {
    /// Call after the files were handed to the outbox (it copies them): removes the prepared temp files and their folders.
    func cleanUp() {
        guard case .files(let drafts, _) = self else { return }
        let fm = FileManager.default, tmp = fm.temporaryDirectory.standardizedFileURL.path
        for d in drafts {
            try? fm.removeItem(at: d.url)
            let folder = d.url.deletingLastPathComponent()
            if folder.standardizedFileURL.path != tmp, folder.standardizedFileURL.path.hasPrefix(tmp),
               (try? fm.contentsOfDirectory(atPath: folder.path))?.isEmpty == true { try? fm.removeItem(at: folder) }
        }
    }
    case files([DraftFile], caption: String?)
    case location(LocationShare)
}

@MainActor
struct MediaPicker: View {
    /// Where the picker opens straight away (the New topic screen's big Photo / Camera buttons); nil = the choices.
    enum Start { case library, camera }
    var onPick: (MediaSelection) -> Void
    var start: Start? = nil
    @Environment(\.dismiss) private var dismiss
    @State private var libraryOpen = false
    @State private var detent: PresentationDetent = .height(170)
    @State private var step: Step = .choices
    @State private var cameraOptions = false
    @State private var capture: Capture?
    @State private var importer = false
    @State private var photos: [PhotosPickerItem] = []
    @State private var drafts: [DraftFile] = []
    @State private var caption = ""
    @State private var errorText: String?
    @State private var busy = false
    @State private var source: Capture?
    @State private var location: LocationShare?
    @State private var address = ""
    @State private var locationProblem: LocationFetcher.Problem?
    @State private var locationRequest = UUID()
    @State private var finished = false

    private enum Step { case choices, preview, location }
    private enum Capture: String, Identifiable { case photo, scan; var id: String { rawValue } }

    init(start: Start? = nil, onPick: @escaping (MediaSelection) -> Void) { self.start = start; self.onPick = onPick }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: step == .choices ? 0 : 16) {
                HStack {
                    Text(title).themeFont(20, .semibold)
                        .fixedSize(horizontal: false, vertical: true).layoutPriority(1)   // never clipped to "Cu…"
                        .accessibilityAddTraits(.isHeader)
                    Spacer()
                    Button { finished = true; removePrepared(drafts); dismiss() } label: {
                        Image(systemName: "xmark").frame(width: 44, height: 44)
                            .background(Theme.surface3, in: Circle())
                    }
                    .buttonStyle(.plain)
                    .foregroundStyle(Theme.muted)
                    .accessibilityLabel("Close media picker")
                    .accessibilityIdentifier("media-close")
                }
                switch step {
                case .choices: choices
                case .preview: preview
                case .location: locationStep
                }
                if busy { ProgressView("Preparing attachments…").tint(Theme.brand).themeFont(14) }
                if let errorText {
                    Text(errorText).themeFont(14).foregroundStyle(Theme.danger)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .padding(.horizontal, 16)
            .padding(.vertical, step == .choices ? 4 : 16)
        }
        .presentationDetents([detent], selection: $detent)
        .presentationDragIndicator(.hidden)   // the close button is the one way out (not both)
        .onChange(of: step) { _, value in
            detent = value == .choices ? .height(170) : .large
        }
        .foregroundStyle(Theme.text)
        .background(Theme.surface)
        .presentationBackground(Theme.surface)
        .preferredColorScheme(.dark)
        .confirmationDialog("Camera", isPresented: $cameraOptions, titleVisibility: .visible) {
            Button("Photo") { source = .photo; capture = .photo }
                .accessibilityLabel("Take photo")
            Button("Scan document") { source = .scan; capture = .scan }
                .disabled(!VNDocumentCameraViewController.isSupported)
                .accessibilityLabel("Scan document")
            Button("Cancel", role: .cancel) {}.accessibilityLabel("Cancel camera")
        }
        .fullScreenCover(item: $capture) { mode in
            if mode == .photo {
                MediaCamera { result in receiveCapture(result, mode: .photo) }.ignoresSafeArea()
            } else {
                MediaScanner { result in receiveCapture(result, mode: .scan) }.ignoresSafeArea()
            }
        }
        .fileImporter(isPresented: $importer, allowedContentTypes: [.item], allowsMultipleSelection: true) { result in
            importFiles(result)
        }
        .onDisappear { if !finished { removePrepared(drafts) } }   // swiped away: nothing prepared stays in the temp folder
        .photosPicker(isPresented: $libraryOpen, selection: $photos, maxSelectionCount: 10, matching: .images)
        .task(id: photos) { await loadPhotos() }
        .task {
            switch start {
            case .camera: if UIImagePickerController.isSourceTypeAvailable(.camera) { source = .photo; capture = .photo }
            case .library:
                #if DEBUG
                if UserDefaults.standard.bool(forKey: "fakePhoto") { receiveCapture(.success([Self.fakeJPEG()]), mode: .photo); source = nil; return }
                #endif
                libraryOpen = true
            case nil: break
            }
        }
        .task(id: locationRequest) {
            if step == .location { await findLocation() }
        }
    }

    private var title: String {
        switch step { case .choices: "Add to chat"; case .preview: "Preview"; case .location: "Current location" }
    }

    private var choices: some View {
        HStack(alignment: .top, spacing: 8) {
            if UIImagePickerController.isSourceTypeAvailable(.camera) {   // no camera: hidden, never a dim tile without a reason
                Button { errorText = nil; cameraOptions = true } label: {
                    MediaTile(label: "Camera", icon: "camera", color: Theme.brand)
                }
                .accessibilityLabel("Camera").accessibilityIdentifier("media-camera")
            }
            photoChoice
            Button {
                errorText = nil
                #if DEBUG
                if UserDefaults.standard.bool(forKey: "fakePhoto") {
                    importFiles(.success([Self.fakePDF()]))
                    return
                }
                #endif
                importer = true
            } label: {
                MediaTile(label: "Files", icon: "doc", color: Theme.warn)
            }
            .accessibilityLabel("Files").accessibilityIdentifier(fileChoiceID)
            Button {
                errorText = nil; step = .location; locationRequest = UUID()
            } label: { MediaTile(label: "Location", icon: "mappin.and.ellipse", color: Theme.brand) }
            .accessibilityLabel("Location").accessibilityIdentifier("media-location")
        }
        .buttonStyle(.plain)
        .disabled(busy)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("media-choices")
    }

    @ViewBuilder private var photoChoice: some View {
        #if DEBUG
        if UserDefaults.standard.bool(forKey: "fakePhoto") {
            Button { errorText = nil; receiveCapture(.success([Self.fakeJPEG()]), mode: .photo) } label: {
                MediaTile(label: "Photos", icon: "photo", color: Theme.purple)
            }
            .accessibilityLabel("Photos").accessibilityIdentifier("media-fake-photo")
        } else {
            libraryChoice
        }
        #else
        libraryChoice
        #endif
    }

    private var libraryChoice: some View {
        PhotosPicker(selection: $photos, maxSelectionCount: 10, matching: .images) {
            MediaTile(label: "Photos", icon: "photo", color: Theme.purple)
        }
        .accessibilityLabel("Photos").accessibilityIdentifier("media-photos")
    }

    private var fileChoiceID: String {
        #if DEBUG
        if UserDefaults.standard.bool(forKey: "fakePhoto") { return "media-fake-pdf" }
        #endif
        return "media-files"
    }

    #if DEBUG
    /// UI tests: the Files browser is out of process; a small PDF in the temp folder goes through the same import path.
    private static func fakePDF() -> URL {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("Offer-Q3.pdf")
        let data = UIGraphicsPDFRenderer(bounds: CGRect(x: 0, y: 0, width: 400, height: 300)).pdfData { c in
            c.beginPage(); ("Offer Q3" as NSString).draw(at: CGPoint(x: 40, y: 120), withAttributes: [.font: UIFont.boldSystemFont(ofSize: 36)])
        }
        try? data.write(to: url)
        return url
    }
    private static func fakeJPEG() -> Data {
        UIGraphicsImageRenderer(size: CGSize(width: 640, height: 480)).jpegData(withCompressionQuality: 0.8) { c in
            UIColor(red: 0.18, green: 0.78, blue: 0.64, alpha: 1).setFill(); c.fill(CGRect(x: 0, y: 0, width: 640, height: 480))
            ("Test photo" as NSString).draw(at: CGPoint(x: 40, y: 200), withAttributes: [.font: UIFont.boldSystemFont(ofSize: 48), .foregroundColor: UIColor.white])
        }
    }
    #endif

    private var preview: some View {
        VStack(spacing: 12) {
            ScrollView(.horizontal) {
                HStack(spacing: 12) {
                    ForEach(drafts, id: \.url) { draft in
                        ZStack(alignment: .topTrailing) {
                            Group {
                                if let image = UIImage(contentsOfFile: draft.url.path) {
                                    Image(uiImage: image).resizable().scaledToFit()
                                } else {
                                    Image(systemName: "photo").foregroundStyle(Theme.muted)
                                }
                            }
                            .frame(width: 240, height: 160)
                            .background(Theme.surface2, in: RoundedRectangle(cornerRadius: Theme.Radius.s, style: .continuous))
                            .accessibilityLabel(draft.name)
                            Button {
                                removePrepared([draft])
                                drafts.removeAll { $0.url == draft.url }
                            } label: {
                                Image(systemName: "xmark").frame(width: 44, height: 44)
                                    .background(Theme.surface3, in: Circle())
                            }
                            .buttonStyle(.plain)
                            .accessibilityLabel("Remove \(draft.name)")
                        }
                    }
                }
            }
            TextField("Add a caption...", text: $caption, axis: .vertical)
                .themeFont(17).padding(12).frame(minHeight: 44)
                .background(Theme.surface2, in: RoundedRectangle(cornerRadius: Theme.Radius.m, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: Theme.Radius.m, style: .continuous).stroke(Theme.border))
                .accessibilityLabel("Add a caption")
                .accessibilityIdentifier("media-caption")
            Button {
                let text = caption.trimmingCharacters(in: .whitespacesAndNewlines)
                pick(.files(drafts, caption: text.isEmpty ? nil : text))
            } label: { Text(drafts.count > 1 ? "Send \(drafts.count) photos" : "Send photo") }
            .buttonStyle(MediaActionStyle(primary: true)).disabled(drafts.isEmpty)
            .accessibilityLabel(drafts.count > 1 ? "Send \(drafts.count) photos" : "Send photo")
            .accessibilityIdentifier("media-send")
            Button {
                removePrepared(drafts)
                drafts = []; caption = ""; errorText = nil; step = .choices
                if let source { capture = source }
                else { photos = [] }
            } label: { Text(source == nil ? "Choose again" : "Retake photo") }
            .buttonStyle(MediaActionStyle())
            .accessibilityLabel(source == nil ? "Choose again" : "Retake photo").accessibilityIdentifier("media-retake")
        }
    }

    private var locationStep: some View {
        VStack(alignment: .leading, spacing: 12) {
            if let location {
                MediaMapPicture(location: location)
                Text(location.label ?? coordinateLabel(location)).themeFont(16, .semibold)
                if !address.isEmpty { Text(address).themeFont(14).foregroundStyle(Theme.muted) }
                Button("Open in Maps") { openMediaLocation(location) }
                    .buttonStyle(MediaActionStyle()).accessibilityLabel("Open in Maps")
                    .accessibilityIdentifier("Open in Maps")
                Button("Share current location") { pick(.location(location)) }
                    .buttonStyle(MediaActionStyle(primary: true))
                    .accessibilityLabel("Share current location").accessibilityIdentifier("media-send")
            } else if let locationProblem {
                Text(locationProblem == .denied ? "Location is off for orch" : locationProblem.localizedDescription)
                    .themeFont(locationProblem == .denied ? 16 : 14, locationProblem == .denied ? .semibold : .regular)
                    .foregroundStyle(locationProblem == .denied ? Theme.text : Theme.danger)
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityIdentifier("location-problem")
                if locationProblem == .denied {
                    Button("Open Settings") {
                        if let url = URL(string: UIApplication.openSettingsURLString) { UIApplication.shared.open(url) }
                    }
                    .buttonStyle(MediaActionStyle()).accessibilityLabel("Open Settings")
                }
                Button("Try again") { locationRequest = UUID() }
                    .buttonStyle(MediaActionStyle(primary: true)).accessibilityLabel("Try again")
            } else {
                VStack(spacing: 12) {
                    ProgressView().tint(Theme.brand)
                    Text("Finding your location…").themeFont(16).foregroundStyle(Theme.muted)
                }
                .frame(maxWidth: .infinity, minHeight: 160).multilineTextAlignment(.center)
                .accessibilityElement(children: .combine)
            }
        }
    }

    private func pick(_ selection: MediaSelection) {
        guard !finished else { return }
        finished = true
        onPick(selection)
        dismiss()
    }

    private func receiveCapture(_ result: Result<[Data], Error>?, mode: Capture) {
        capture = nil
        guard let result else { return }
        errorText = nil
        do {
            let data = try result.get()
            guard !data.isEmpty else { throw MediaPrep.Problem.empty }
            guard data.count <= 10 else { throw MediaPickerProblem.tooMany }
            var prepared: [DraftFile] = []
            do {
                for (index, bytes) in data.enumerated() {
                    prepared.append(try MediaPrep.photoDraft(from: bytes, name: mode == .photo ? "photo.jpg" : "scan-\(index + 1).jpg"))
                }
            } catch {
                removePrepared(prepared)
                throw error
            }
            drafts = prepared; caption = ""; source = mode; step = .preview
        } catch { errorText = error.localizedDescription }
    }

    private func loadPhotos() async {
        guard !photos.isEmpty else { return }
        busy = true; errorText = nil
        defer { busy = false }
        var prepared: [DraftFile] = []
        do {
            for (index, item) in photos.enumerated() {
                try Task.checkCancellation()
                guard let data = try await item.loadTransferable(type: Data.self) else { throw MediaPrep.Problem.notAnImage }
                try Task.checkCancellation()
                prepared.append(try MediaPrep.photoDraft(from: data, name: "photo-\(index + 1).jpg"))
            }
            guard !finished else { removePrepared(prepared); return }
            drafts = prepared; caption = ""; source = nil; step = .preview
        } catch {
            removePrepared(prepared)
            if !(error is CancellationError) { errorText = error.localizedDescription }
        }
    }

    private func importFiles(_ result: Result<[URL], Error>) {
        errorText = nil
        var prepared: [DraftFile] = []
        var folders: [URL] = []
        do {
            let urls = try result.get()
            guard !urls.isEmpty else { return }
            guard urls.count <= 10 else { throw MediaPickerProblem.tooMany }
            for url in urls {
                let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
                folders.append(folder)
                try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
                let local = folder.appendingPathComponent(url.lastPathComponent)
                let scoped = url.startAccessingSecurityScopedResource()
                let type: UTType?
                do {
                    defer { if scoped { url.stopAccessingSecurityScopedResource() } }
                    type = (try? url.resourceValues(forKeys: [.contentTypeKey]))?.contentType
                        ?? UTType(filenameExtension: url.pathExtension)
                    try FileManager.default.copyItem(at: url, to: local)
                }
                if type?.conforms(to: .image) == true {
                    prepared.append(try MediaPrep.photoDraft(from: Data(contentsOf: local), name: url.lastPathComponent, directory: folder))
                    try? FileManager.default.removeItem(at: local)
                } else {
                    prepared.append(try MediaPrep.fileDraft(at: local))
                }
            }
            pick(.files(prepared, caption: nil))
        } catch {
            for folder in folders { try? FileManager.default.removeItem(at: folder) }
            errorText = error.localizedDescription
        }
    }

    private func findLocation() async {
        location = nil; locationProblem = nil
        #if DEBUG
        if UserDefaults.standard.bool(forKey: "fakeLocation") {
            address = "1 Infinite Loop, Cupertino"
            location = LocationShare(lat: 37.3317, lon: -122.0301, label: "Infinite Loop", accuracyM: 10)
            return
        }
        #endif
        let fetcher = LocationFetcher()
        do {
            let share = try await fetcher.current()
            try Task.checkCancellation()
            let geocoder = CLGeocoder()
            let placemark = try? await geocoder.reverseGeocodeLocation(CLLocation(latitude: share.lat, longitude: share.lon)).first
            try Task.checkCancellation()
            let fallback = coordinateLabel(share)
            let name = placemark?.name ?? fallback
            let street = [placemark?.thoroughfare, placemark?.subThoroughfare].compactMap { $0 }.joined(separator: " ")
            address = [street.isEmpty ? nil : street, placemark?.locality].compactMap { $0 }.joined(separator: ", ")
            location = LocationShare(lat: share.lat, lon: share.lon, label: String(name.prefix(200)), accuracyM: share.accuracyM)
        } catch {
            if !(error is CancellationError) { locationProblem = (error as? LocationFetcher.Problem) ?? .unavailable }
        }
    }

    private func removePrepared(_ files: [DraftFile]) {
        for file in files { try? FileManager.default.removeItem(at: file.url) }
    }
}

private enum MediaPickerProblem: LocalizedError {
    case tooMany
    var errorDescription: String? { "Choose up to 10 attachments at a time." }
}

@MainActor
private struct MediaActionStyle: ButtonStyle {
    var primary = false
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.themeFont(17, .semibold)
            .frame(maxWidth: .infinity, minHeight: 44).padding(.vertical, 4).padding(.horizontal, 12)
            .foregroundStyle(primary ? Theme.onBrand : Theme.text)
            .background(primary ? Theme.brand : Theme.surface3, in: RoundedRectangle(cornerRadius: Theme.Radius.m, style: .continuous))
            .opacity(configuration.isPressed ? 0.75 : 1)
    }
}

@MainActor
private struct MediaCamera: UIViewControllerRepresentable {
    let completion: @MainActor (Result<[Data], Error>?) -> Void
    func makeCoordinator() -> Coordinator { Coordinator(completion: completion) }
    func makeUIViewController(context: Context) -> UIImagePickerController {
        let picker = UIImagePickerController()
        picker.sourceType = .camera
        picker.mediaTypes = [UTType.image.identifier]
        picker.delegate = context.coordinator
        return picker
    }
    func updateUIViewController(_ controller: UIImagePickerController, context: Context) {}

    @MainActor
    final class Coordinator: NSObject, UIImagePickerControllerDelegate, UINavigationControllerDelegate {
        let completion: @MainActor (Result<[Data], Error>?) -> Void
        init(completion: @escaping @MainActor (Result<[Data], Error>?) -> Void) { self.completion = completion }
        nonisolated func imagePickerControllerDidCancel(_ picker: UIImagePickerController) {
            Task { @MainActor in self.completion(nil) }
        }
        nonisolated func imagePickerController(_ picker: UIImagePickerController, didFinishPickingMediaWithInfo info: [UIImagePickerController.InfoKey: Any]) {
            let data = (info[.originalImage] as? UIImage)?.jpegData(compressionQuality: 1)
            Task { @MainActor in
                if let data { self.completion(.success([data])) }
                else { self.completion(.failure(MediaPrep.Problem.notAnImage)) }
            }
        }
    }
}

@MainActor
private struct MediaScanner: UIViewControllerRepresentable {
    let completion: @MainActor (Result<[Data], Error>?) -> Void
    func makeCoordinator() -> Coordinator { Coordinator(completion: completion) }
    func makeUIViewController(context: Context) -> VNDocumentCameraViewController {
        let controller = VNDocumentCameraViewController()
        controller.delegate = context.coordinator
        return controller
    }
    func updateUIViewController(_ controller: VNDocumentCameraViewController, context: Context) {}

    @MainActor
    final class Coordinator: NSObject, VNDocumentCameraViewControllerDelegate {
        let completion: @MainActor (Result<[Data], Error>?) -> Void
        init(completion: @escaping @MainActor (Result<[Data], Error>?) -> Void) { self.completion = completion }
        nonisolated func documentCameraViewControllerDidCancel(_ controller: VNDocumentCameraViewController) {
            Task { @MainActor in self.completion(nil) }
        }
        nonisolated func documentCameraViewController(_ controller: VNDocumentCameraViewController, didFailWithError error: Error) {
            Task { @MainActor in self.completion(.failure(error)) }
        }
        nonisolated func documentCameraViewController(_ controller: VNDocumentCameraViewController, didFinishWith scan: VNDocumentCameraScan) {
            let result: Result<[Data], Error>
            do {
                guard scan.pageCount <= 10 else { throw MediaPickerProblem.tooMany }
                result = .success(try (0..<scan.pageCount).map { index in
                    guard let data = scan.imageOfPage(at: index).jpegData(compressionQuality: 1) else { throw MediaPrep.Problem.notAnImage }
                    return data
                })
            } catch { result = .failure(error) }
            Task { @MainActor in self.completion(result) }
        }
    }
}

/// A map picture of a place with the place name and an action to open Maps.
@MainActor
struct LocationCard: View {
    let location: LocationShare
    init(location: LocationShare) { self.location = location }
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            MediaMapPicture(radius: Theme.Radius.m - 12, location: location)
            Text(location.label ?? coordinateLabel(location)).themeFont(16, .semibold)
            Button("Open in Maps") { openMediaLocation(location) }
                .buttonStyle(MediaActionStyle()).accessibilityLabel("Open in Maps")
                .accessibilityIdentifier("Open in Maps")
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(12).foregroundStyle(Theme.text)
        .background(Theme.surface2, in: RoundedRectangle(cornerRadius: Theme.Radius.m, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: Theme.Radius.m, style: .continuous).stroke(Theme.border))
    }
}

private func coordinateLabel(_ location: LocationShare) -> String {
    String(format: "%.4f, %.4f", location.lat, location.lon)
}

@MainActor
private func openMediaLocation(_ location: LocationShare) {
    let item = MKMapItem(placemark: MKPlacemark(coordinate: CLLocationCoordinate2D(latitude: location.lat, longitude: location.lon)))
    item.name = location.label ?? coordinateLabel(location)
    item.openInMaps()
}

@MainActor
private struct MediaMapPicture: View {
    var radius: CGFloat = Theme.Radius.m
    let location: LocationShare
    @State private var picture: UIImage?
    private static var cache: [String: UIImage] = [:]
    private var key: String { String(format: "%.5f,%.5f", location.lat, location.lon) }

    var body: some View {
        // The picture only fills an overlay: a scaledToFill image as the view itself made the card wider than the screen.
        Theme.surface2
            .overlay {
                if let picture { Image(uiImage: picture).resizable().scaledToFill() }
                else { Image(systemName: "mappin.and.ellipse").foregroundStyle(Theme.brand).themeFont(28) }
            }
        .frame(height: 130).frame(maxWidth: .infinity)
        .clipped().clipShape(RoundedRectangle(cornerRadius: radius, style: .continuous))
        .accessibilityLabel("Map of \(location.label ?? coordinateLabel(location))")
        .task(id: key) { await snapshot() }
    }

    private func snapshot() async {
        let cacheKey = key
        picture = Self.cache[cacheKey]
        guard picture == nil else { return }
        let coordinate = CLLocationCoordinate2D(latitude: location.lat, longitude: location.lon)
        let options = MKMapSnapshotter.Options()
        options.size = CGSize(width: 340, height: 130)
        options.region = MKCoordinateRegion(center: coordinate, latitudinalMeters: 400, longitudinalMeters: 400)
        options.traitCollection = UITraitCollection(userInterfaceStyle: .dark)
        let snapshotter = MKMapSnapshotter(options: options)
        // Only image bytes and a Sendable point cross the callback boundary.
        let result: (Data, CGPoint)? = await withCheckedContinuation { continuation in
            snapshotter.start { snapshot, _ in
                guard let snapshot, let data = snapshot.image.pngData() else {
                    continuation.resume(returning: nil)
                    return
                }
                continuation.resume(returning: (data, snapshot.point(for: coordinate)))
            }
        }
        guard !Task.isCancelled, let (data, point) = result, let base = UIImage(data: data) else { return }
        let image = UIGraphicsImageRenderer(size: base.size).image { context in
            base.draw(at: .zero)
            let rect = CGRect(x: point.x - 8, y: point.y - 8, width: 16, height: 16)
            UIColor(Theme.brand).setFill()
            context.cgContext.fillEllipse(in: rect)
            UIColor.white.setStroke()
            context.cgContext.setLineWidth(2)
            context.cgContext.strokeEllipse(in: rect)
        }
        Self.cache[cacheKey] = image
        picture = image
    }
}

/// One source tile (a struct, not a method: the PhotosPicker label closure is not main-actor isolated).
private struct MediaTile: View {
    let label: String
    let icon: String
    let color: Color
    var body: some View {
        VStack(spacing: 8) {
            Image(systemName: icon).themeFont(22).foregroundStyle(color)
                .frame(width: 56, height: 56)
                .background(Theme.surface2, in: RoundedRectangle(cornerRadius: Theme.Radius.avatar(56), style: .continuous))
            Text(label).themeFont(13).fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, minHeight: 88)
        .contentShape(Rectangle())
    }
}
