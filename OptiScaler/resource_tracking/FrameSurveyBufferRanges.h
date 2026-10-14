#pragma once
#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <memory>
#include <utility>

namespace FrameSurveyMetadata
{
// Live GPU-VA intervals, including placed buffers that overlap or share a start.
// The caller serializes access with the resource registry's lifetime lock.
class BufferAddressIndex
{
    struct Node
    {
        uint64_t start, generation, last, maximum, priority;
        void* object;
        std::unique_ptr<Node> left, right;
        Node(uint64_t address, uint64_t bytes, uint64_t identity, void* value)
            : start(address), generation(identity),
              last(bytes-1 > UINT64_MAX-address ? UINT64_MAX : address+bytes-1), maximum(last),
              priority(Priority(identity)), object(value) {}
        static uint64_t Priority(uint64_t identity) noexcept
        {
            // Deterministic mixing keeps sequential resource generations balanced.
            identity += 0x9e3779b97f4a7c15ull;
            identity = (identity^(identity>>30))*0xbf58476d1ce4e5b9ull;
            identity = (identity^(identity>>27))*0x94d049bb133111ebull;
            return identity^(identity>>31);
        }
        auto Key() const noexcept { return std::pair(start,generation); }
        void Update() noexcept
        {
            maximum = last;
            if (left) maximum = std::max(maximum,left->maximum);
            if (right) maximum = std::max(maximum,right->maximum);
        }
    };
    using Tree = std::unique_ptr<Node>;
    Tree root_;
    size_t size_ = 0;
    static void RotateLeft(Tree& root) noexcept
    {
        auto next = std::move(root->right);
        root->right = std::move(next->left); root->Update();
        next->left = std::move(root); next->Update(); root = std::move(next);
    }
    static void RotateRight(Tree& root) noexcept
    {
        auto next = std::move(root->left);
        root->left = std::move(next->right); root->Update();
        next->right = std::move(root); next->Update(); root = std::move(next);
    }
    static bool InsertNode(Tree& root, Tree node) noexcept
    {
        if (!root) { root = std::move(node); return true; }
        bool inserted = false;
        if (node->Key() < root->Key())
        {
            inserted = InsertNode(root->left,std::move(node));
            if (root->left->priority < root->priority) RotateRight(root);
        }
        else if (root->Key() < node->Key())
        {
            inserted = InsertNode(root->right,std::move(node));
            if (root->right->priority < root->priority) RotateLeft(root);
        }
        else { root->last = node->last; root->object = node->object; }
        root->Update(); return inserted;
    }
    static Tree Join(Tree left, Tree right) noexcept
    {
        if (!left) return right;
        if (!right) return left;
        if (left->priority < right->priority)
        { left->right = Join(std::move(left->right),std::move(right)); left->Update(); return left; }
        right->left = Join(std::move(left),std::move(right->left)); right->Update(); return right;
    }
    static bool EraseNode(Tree& root, std::pair<uint64_t,uint64_t> key) noexcept
    {
        if (!root) return false;
        bool erased = false;
        if (key < root->Key()) erased = EraseNode(root->left,key);
        else if (root->Key() < key) erased = EraseNode(root->right,key);
        else { root = Join(std::move(root->left),std::move(root->right)); return true; }
        root->Update(); return erased;
    }
  public:
    struct Match
    {
        void* object = nullptr;
        uint64_t generation = 0;
        size_t visited = 0;
        unsigned matches = 0;
    };
  private:
    static void FindNode(const Node* node, uint64_t address, Match& result) noexcept
    {
        if (!node || result.matches >= 2) return;
        ++result.visited;
        if (node->maximum < address) return;
        FindNode(node->left.get(),address,result);
        if (result.matches >= 2 || node->start > address) return;
        if (address <= node->last)
        { result.object = node->object; result.generation = node->generation; ++result.matches; }
        FindNode(node->right.get(),address,result);
    }
  public:
    void Insert(uint64_t start, uint64_t bytes, uint64_t generation, void* object)
    {
        if (!start || !bytes || !generation || !object) return;
        if (InsertNode(root_,std::make_unique<Node>(start,bytes,generation,object))) ++size_;
    }
    void Erase(uint64_t start, uint64_t generation) noexcept
    { if (EraseNode(root_,{start,generation})) --size_; }
    void Clear() noexcept { root_.reset(); size_ = 0; }
    size_t Size() const noexcept { return size_; }
    Match Find(uint64_t address) const noexcept
    {
        Match result; FindNode(root_.get(),address,result);
        if (result.matches != 1) { result.object = nullptr; result.generation = 0; }
        return result;
    }
};
}
